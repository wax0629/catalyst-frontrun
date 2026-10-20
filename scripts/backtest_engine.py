#!/usr/bin/env python3
"""
尾盘隔夜策略回测引擎 (Backtest Engine v0.1)
严格无未来函数 (No Look-Ahead Bias):
在 T 日 14:40 做出决策前，绝不读取 T+1 日任何价格与行情！
决策冻结后，才进入 T+1 日早盘出场检验。
"""
import os
import sys
import json
import pandas as pd
import baostock as bs
import datetime

# 导入流水线
from tail_overnight_pipeline import (
    get_market_regime_snapshot,
    get_candidate_pool,
    evaluate_stock_snapshots,
    synthesize_layer5_decision
)

def fetch_stock_history_baostock(code: str, start_date: str, end_date: str) -> pd.DataFrame:
    """获取标的历史日 K 线"""
    prefix = "sh" if code.startswith("6") or code.startswith("5") or code.startswith("9") else "sz"
    bs_code = f"{prefix}.{code}"
    
    # 格式化日期为 YYYY-MM-DD
    s_fmt = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}"
    e_fmt = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}"
    
    rs = bs.query_history_k_data_plus(
        bs_code,
        "date,open,high,low,close,preclose,amount,pctChg",
        start_date=s_fmt, end_date=e_fmt, frequency="d"
    )
    rows = []
    while rs.error_code == '0' and rs.next():
        rows.append(rs.get_row_data())
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=['date', 'open', 'high', 'low', 'close', 'preclose', 'amount', 'pctChg'])
    df['date'] = df['date'].str.replace('-', '')
    return df

def run_single_day_test(prev_date: str, trade_date: str, next_date: str) -> dict:
    """运行单日无未来函数点时测试 (T-1日涨停池取种子 -> T日14:40全息决策 -> T+1日早盘检验)"""
    print(f"\n================================================================================")
    print(f" 📅 【测试交易日 T 日】: {trade_date} (前一交易日 T-1: {prev_date} | 次日开盘日 T+1: {next_date})")
    print(f"================================================================================")
    
    # 1. 运行第 1 层: 大盘环境排雷快照 (严格在 T 日 14:40 触发)
    market_snap = get_market_regime_snapshot(trade_date)
    print(f"📋 快照 1 (大盘环境): {market_snap['summary']}")
    
    # 2. 获取候选池 (从 T-1 日涨停池中提取种子标的)
    candidates = get_candidate_pool(prev_date)
    print(f"🔍 候选池规模 (T-1 日涨停池): 成功获取 {len(candidates)} 只种子标的")
    if not candidates:
        print("未获取到候选种子，跳过测试。")
        return {"date": trade_date, "status": "NO_CANDIDATES"}

    # 3. 对前 25 只高活跃种子，严格按 T 日数据生成第 2~4 层快照 (严禁偷看 T+1)
    eval_list = []
    start_lookback = (datetime.datetime.strptime(trade_date, "%Y%m%d") - datetime.timedelta(days=20)).strftime("%Y%m%d")
    
    for c in candidates[:25]:
        code = c["code"]
        name = c["name"]
        reason = c["reason"]
        
        # 仅拉取截至 T 日的 K 线
        df_kline = fetch_stock_history_baostock(code, start_lookback, trade_date)
        if df_kline.empty:
            continue
            
        ev = evaluate_stock_snapshots(code, name, trade_date, reason, df_kline)
        if ev:
            eval_list.append(ev)
            
    print(f"📊 完成单股客观快照体检: {len(eval_list)} 只标的已生成结构化档案")

    # 4. 运行第 5 层: 统筹宏观与快照生成决策
    decisions = synthesize_layer5_decision(eval_list, market_snap)
    
    # 筛选出推荐买入标的
    buy_targets = [d for d in decisions if d["action"] == "BUY"]
    print(f"\n🧠 【第 5 层决策裁定】: 选出 {len(buy_targets)} 只建议买入标的 (BUY)")
    
    for d in decisions[:4]:
        print(f"  • [{d['action']:6s}] {d['name']} ({d['code']}): 评级分={d['total_score']}分 | 现价={d['close_price']:.2f}元")
        print(f"    - 理由: {d['thesis']}")

    # ----------------------------------------------------------------------------------
    # 严格分水岭: 只有到这里，T 日决策彻底冻结，绝不再更改！
    # 下方才开始读取 T+1 日（次日）真实开盘与早盘数据进行验证！
    # ----------------------------------------------------------------------------------
    print(f"\n⏱️ 【进入 T+1 日 ({next_date}) 次日实盘表现严格验证】:")
    
    if not buy_targets:
        print(f"💡 本日策略系统判定为【空仓防守 / PASS】(避险生效)，无买入标的。")
        return {
            "date": trade_date,
            "next_date": next_date,
            "market_passed": market_snap["passed"],
            "decision": "NO_BUY",
            "trades": []
        }
        
    trades_eval = []
    for target in buy_targets[:2]: # 每天最多开仓前 2 只
        code = target["code"]
        name = target["name"]
        buy_price = target["close_price"]
        
        # 此时才拉取 T+1 日的 K 线
        df_next = fetch_stock_history_baostock(code, trade_date, next_date)
        row_next = df_next[df_next['date'] == next_date]
        if row_next.empty:
            continue
            
        row_t1 = row_next.iloc[0]
        open_t1 = float(row_t1['open'])
        high_t1 = float(row_t1['high'])
        low_t1 = float(row_t1['low'])
        close_t1 = float(row_t1['close'])
        
        # 计算次日开盘表现
        open_gain_pct = round((open_t1 - buy_price) / buy_price * 100, 2)
        max_intraday_gain = round((high_t1 - buy_price) / buy_price * 100, 2)
        min_intraday_gain = round((low_t1 - buy_price) / buy_price * 100, 2)
        
        # 按照早盘出场规则模拟撮合
        # 1. 检查是否触及 -3.0% 硬止损
        is_hard_stop = (min_intraday_gain <= -3.0)
        # 2. 检查是否冲高突破 +2.0% 激活平保
        is_ratchet_active = (max_intraday_gain >= 2.0)
        
        # 退出收益率评估
        if is_hard_stop and open_gain_pct < -3.0:
            exit_gain = open_gain_pct # 低开跳空直接止损
            exit_reason = "🚨 开盘深度低开止损"
        elif is_hard_stop and not is_ratchet_active:
            exit_gain = -3.0
            exit_reason = "🚨 盘中跌破 -3.0% 硬止损"
        elif is_ratchet_active:
            # 吊灯止盈: 最高点回落 1.5% 出局
            exit_gain = max_intraday_gain - 1.5
            exit_reason = f"🎯 冲高至 +{max_intraday_gain}% 触发吊灯止盈"
        else:
            # 10:00 时间熔断: 接近开盘或收盘平价出局
            exit_gain = open_gain_pct
            exit_reason = "⌛ 10:00 时间熔断平价出局"
            
        is_win = (exit_gain > 0)
        print(f"  👉 标的: {name} ({code}) | 买入价={buy_price:.2f}元")
        print(f"     * 次日开盘: {open_t1:.2f}元 (高/低开: {open_gain_pct:+.2f}%)")
        print(f"     * 次日早盘最高: {high_t1:.2f}元 (最大冲高: {max_intraday_gain:+.2f}%) | 最低: {low_t1:.2f}元")
        print(f"     * 最终执行出局: 收益率={exit_gain:+.2f}% ({exit_reason}) | 胜负: {'✅ 盈利' if is_win else '❌ 亏损'}")
        
        trades_eval.append({
            "code": code,
            "name": name,
            "buy_price": buy_price,
            "open_gain": open_gain_pct,
            "exit_gain": exit_gain,
            "is_win": is_win,
            "exit_reason": exit_reason
        })
        
    return {
        "date": trade_date,
        "next_date": next_date,
        "market_passed": market_snap["passed"],
        "decision": "BOUGHT",
        "trades": trades_eval
    }

def run_multi_day_backtest():
    """多月度随机抽样点时回测"""
    bs.login()
    
    # 随机抽样 6 个跨不同月份的交易日
    # 涵盖: 震荡市、主升市、退潮市
    sample_triplets = [
        ("20260225", "20260226", "20260227"), # 2月下旬 稳健主升
        ("20260408", "20260409", "20260410"), # 4月上旬 题材活跃
        ("20260624", "20260625", "20260626"), # 6月下旬 暴跌退潮 (检验防守)
        ("20260826", "20260827", "20260828"), # 8月下旬 正常震荡
        ("20260923", "20260924", "20260928"), # 9月下旬 踩踏前夕 (检验防守)
        ("20261016", "20261019", "20261020"), # 昨天 (刚刚实操的真实样本)
    ]
    
    all_trades = []
    days_summary = []
    
    for prev_date, t_date, next_date in sample_triplets:
        res = run_single_day_test(prev_date, t_date, next_date)
        days_summary.append(res)
        all_trades.extend(res.get("trades", []))
        
    bs.logout()
    
    # 综合绩效结算
    print(f"\n================================================================================")
    print(f" 📈 【尾盘隔夜策略 v0.1 多月度抽样回测总决算】")
    print(f"================================================================================")
    
    total_days = len(sample_triplets)
    open_days = len([d for d in days_summary if d.get("decision") == "BOUGHT"])
    pass_days = total_days - open_days
    
    print(f"• 测试总天数: {total_days} 个独立交易日")
    print(f"• 大盘门禁系统执行空仓防守: {pass_days} 天 (避险率 {pass_days/total_days*100:.1f}%)")
    print(f"• 触发买入开仓交易日: {open_days} 天")
    
    if all_trades:
        total_trades = len(all_trades)
        wins = len([t for t in all_trades if t["is_win"]])
        win_rate = (wins / total_trades) * 100
        avg_open_gain = sum(t["open_gain"] for t in all_trades) / total_trades
        avg_exit_gain = sum(t["exit_gain"] for t in all_trades) / total_trades
        
        print(f"• 总成交单数: {total_trades} 笔")
        print(f"• 次日开盘平均涨幅 (高开溢价): {avg_open_gain:+.2f}%")
        print(f"• 执行纪律最终平仓平均收益率: {avg_exit_gain:+.2f}%")
        print(f"• 【最终策略胜率 (Win Rate)】: {win_rate:.1f}% ({wins}胜 / {total_trades-wins}负)")
    else:
        print("所有样本日均被风控系统拦截保护，未产生实盘开仓。")
    print(f"================================================================================\n")

if __name__ == '__main__':
    run_multi_day_backtest()
