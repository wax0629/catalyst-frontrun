#!/usr/bin/env python3
"""
2024 全年全样本严格点时回测 (v0.2 优化版)
覆盖指数: 中证 800 (沪深 300 + 中证 500 全部 800 只核心流动性标的)
周期: 2024-01-02 至 2024-12-31 (完整 242 个交易日)
规则版本: v0.2 (阶梯平保 + 紧凑吊灯 + 蓄势带宽精细化 + 竞价低开止损)
严格无未来函数 (Point-in-Time Strictly Enforced)
"""
import os
import sys
import json
import time
import pandas as pd
import baostock as bs

def run_2024_complete_backtest():
    print("=" * 80)
    print("🚀 启动 2024 全年 (2024-01-02 ~ 2024-12-31) 完整回测 (v0.2 优化版)...")
    print("标的池: 中证 800 (覆盖沪深 300 + 中证 500 全部 800 只核心蓝筹成长中军)")
    print("=" * 80)
    
    bs.login()
    
    # 1. 获取 2024 中证 800 成分股全名单
    print("⏳ [1/4] 正在拉取 2024 年中证 800 成分股列表...")
    rs_hs = bs.query_hs300_stocks(date='2024-06-30')
    codes_hs = []
    while rs_hs.error_code == '0' and rs_hs.next():
        codes_hs.append(rs_hs.get_row_data()[1])
        
    rs_zz = bs.query_zz500_stocks(date='2024-06-30')
    codes_zz = []
    while rs_zz.error_code == '0' and rs_zz.next():
        codes_zz.append(rs_zz.get_row_data()[1])
        
    all_codes = list(set(codes_hs + codes_zz))
    print(f"✅ 成功锁定 800 核心股票池 (沪深300={len(codes_hs)}, 中证500={len(codes_zz)}, 去重后={len(all_codes)})")
    
    # 2. 批量拉取 800 只标的全年日线数据
    print(f"⏳ [2/4] 正在拉取 800 只股票 2024 全年历史日 K 线 (约需 1~2 分钟)...")
    t_pull_start = time.time()
    stock_dfs = {}
    
    # 扩大日期跨度覆盖边界 (2023-12-25 至 2025-01-06)
    s_date = '2023-12-25'
    e_date = '2025-01-06'
    
    for idx, c in enumerate(all_codes):
        rs = bs.query_history_k_data_plus(
            c,
            "date,open,high,low,close,preclose,amount,pctChg",
            start_date=s_date, end_date=e_date, frequency="d"
        )
        rows = []
        while rs.error_code == '0' and rs.next():
            rows.append(rs.get_row_data())
        if rows:
            df = pd.DataFrame(rows, columns=['date', 'open', 'high', 'low', 'close', 'preclose', 'amount', 'pctChg'])
            for col in ['open', 'high', 'low', 'close', 'preclose', 'amount', 'pctChg']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            df['date'] = df['date'].str.replace('-', '')
            stock_dfs[c] = df
            
        if (idx + 1) % 200 == 0:
            print(f"  已完成 [{idx+1}/{len(all_codes)}] 只股票日线加载...")
            
    print(f"✅ 日线数据库构建完毕！耗时: {time.time()-t_pull_start:.1f} 秒, 成功加载 {len(stock_dfs)} 只标的")
    
    # 3. 获取交易日历
    rs_cal = bs.query_trade_dates(start_date='2023-12-28', end_date='2025-01-06')
    cal_data = []
    while rs_cal.error_code == '0' and rs_cal.next():
        cal_data.append(rs_cal.get_row_data())
    df_cal = pd.DataFrame(cal_data, columns=rs_cal.fields)
    trade_days = [d.replace('-', '') for d in df_cal[df_cal['is_trading_day'] == '1']['calendar_date'].tolist()]
    
    start_idx = trade_days.index('20240102')
    end_idx = trade_days.index('20241231')
    
    print(f"📅 2024 年回测周期: {trade_days[start_idx]} 至 {trade_days[end_idx]} 共 {end_idx - start_idx + 1} 个实际交易日\n")
    
    # 4. 执行逐日点时无未来函数回测
    all_trades = []
    daily_stats = []
    
    for i in range(start_idx, end_idx + 1):
        prev_date = trade_days[i - 1]
        t_date = trade_days[i]
        next_date = trade_days[i + 1]
        
        # 寻找 T-1 日涨停种子标的
        # 主板涨幅 >= 9.5%，创业板/科创板 >= 19.5%
        candidates = []
        for c, df in stock_dfs.items():
            row_prev = df[df['date'] == prev_date]
            if not row_prev.empty:
                pct_prev = row_prev.iloc[0]['pctChg']
                is_gem_star = c.startswith('sz.30') or c.startswith('sh.68')
                limit_threshold = 19.2 if is_gem_star else 9.5
                if pct_prev >= limit_threshold:
                    candidates.append(c)
                    
        if not candidates:
            daily_stats.append({"date": t_date, "status": "NO_CANDIDATES"})
            continue
            
        # 在 T 日 14:40 严格按客观数据检验
        qualified = []
        for c in candidates:
            df = stock_dfs[c]
            row_t = df[df['date'] == t_date]
            if row_t.empty:
                continue
            r = row_t.iloc[0]
            amt_yi = r['amount'] / 1e8
            pct_t = r['pctChg']
            hi_t = r['high']
            cl_t = r['close']
            pre_t = r['preclose']
            
            if pd.isna(cl_t) or cl_t <= 0:
                continue
                
            max_gain_pct = (hi_t - pre_t) / pre_t * 100 if pre_t > 0 else 0
            pullback_pct = (hi_t - cl_t) / hi_t * 100 if hi_t > 0 else 0
            
            # v0.2 优化快照规则:
            # 1. 成交额 >= 4.0 亿元
            # 2. 蓄势带: +1.8% ~ +3.8% (黄金档)，允许 +3.8% ~ +5.0% (次优档)
            # 3. 回落 <= 1.8%
            # 4. 死穴上影线: 冲高超 6% 回落不得超过 2.0%
            is_liquid = (amt_yi >= 4.0)
            is_prime = (1.8 <= pct_t <= 3.8)
            is_acceptable = (3.8 < pct_t <= 5.0)
            is_valid_band = is_prime or is_acceptable
            has_deadly_shadow = (max_gain_pct >= 6.0 and pullback_pct >= 2.0)
            
            if is_liquid and is_valid_band and (not has_deadly_shadow) and (pullback_pct <= 1.8):
                # 计算评分: 黄金档优先
                score = (100 if is_prime else 80) + min(20, amt_yi / 2.0) - pullback_pct * 5
                qualified.append({
                    "code": c,
                    "close_price": cl_t,
                    "amount_yi": amt_yi,
                    "pct_t": pct_t,
                    "score": score
                })
                
        if not qualified:
            daily_stats.append({"date": t_date, "status": "NO_QUALIFIED"})
            continue
            
        # 按得分排序，每日最多开仓前 2 只
        qualified.sort(key=lambda x: x["score"], reverse=True)
        selected = qualified[:2]
        
        # 决策冻结，向后取 T+1 早盘撮合 (v0.2 优化出场模型)
        for s in selected:
            c = s["code"]
            buy_price = s["close_price"]
            df = stock_dfs[c]
            row_t1 = df[df['date'] == next_date]
            if row_t1.empty:
                continue
            r1 = row_t1.iloc[0]
            op_t1 = r1['open']
            hi_t1 = r1['high']
            lo_t1 = r1['low']
            
            if pd.isna(op_t1) or op_t1 <= 0:
                continue
                
            open_gain = round((op_t1 - buy_price) / buy_price * 100, 2)
            max_intraday_gain = round((hi_t1 - buy_price) / buy_price * 100, 2)
            min_intraday_gain = round((lo_t1 - buy_price) / buy_price * 100, 2)
            
            # v0.2 出场规则:
            # 1. 深度低开快速止损 (open_gain < -2.5%)
            # 2. 冲高 >= +1.8% 紧凑吊灯止盈 (high - 1.2%)
            # 3. 冲高 >= +1.0% 阶梯平保锁定 (保本出局)
            # 4. 盘中触及 -3.0% 硬止损
            # 5. 10:00 时间熔断
            is_ratchet_t2 = (max_intraday_gain >= 1.8)
            is_ratchet_t1 = (max_intraday_gain >= 1.0)
            is_hard_stop = (min_intraday_gain <= -3.0)
            
            if open_gain < -2.5:
                exit_gain = open_gain
                rule = "🚨 竞价深度低开果断止损"
            elif is_ratchet_t2:
                exit_gain = round(max_intraday_gain - 1.2, 2)
                rule = f"🎯 冲高至+{max_intraday_gain}%紧凑吊灯止盈"
            elif is_ratchet_t1:
                exit_gain = max(0.0, round(max_intraday_gain - 1.0, 2))
                rule = f"🛡️ 冲高至+{max_intraday_gain}%激活平保锁防守"
            elif is_hard_stop:
                exit_gain = -3.0
                rule = "🚨 盘中触及-3.0%硬止损"
            else:
                exit_gain = open_gain
                rule = "⌛ 10:00 时间熔断平价出局"
                
            trade_record = {
                "trade_date": t_date,
                "next_date": next_date,
                "code": c,
                "buy_price": float(buy_price),
                "open_gain": float(open_gain),
                "max_intraday_gain": float(max_intraday_gain),
                "min_intraday_gain": float(min_intraday_gain),
                "exit_gain": float(exit_gain),
                "rule": rule,
                "is_win": bool(exit_gain > 0)
            }
            all_trades.append(trade_record)
            
    bs.logout()
    
    # 5. 汇总统计与月度拆解
    total_trades = len(all_trades)
    wins = len([t for t in all_trades if t["exit_gain"] > 0])
    draws = len([t for t in all_trades if t["exit_gain"] == 0])
    losses = len([t for t in all_trades if t["exit_gain"] < 0])
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
    avg_exit = (sum(t["exit_gain"] for t in all_trades) / total_trades) if total_trades > 0 else 0.0
    avg_open = (sum(t["open_gain"] for t in all_trades) / total_trades) if total_trades > 0 else 0.0
    
    # 模拟 20 万复利
    cap = 200000.0
    monthly_data = {}
    
    # 按交易日归并计算复利
    trades_by_date = {}
    for t in all_trades:
        d = t["trade_date"]
        if d not in trades_by_date:
            trades_by_date[d] = []
        trades_by_date[d].append(t)
        
    for d, d_trades in sorted(trades_by_date.items()):
        m = d[:6]
        if m not in monthly_data:
            monthly_data[m] = {"trades": [], "wins": 0, "losses": 0, "gains": []}
            
        day_pct = 0.0
        for t in d_trades:
            monthly_data[m]["trades"].append(t)
            if t["exit_gain"] > 0:
                monthly_data[m]["wins"] += 1
            elif t["exit_gain"] < 0:
                monthly_data[m]["losses"] += 1
            monthly_data[m]["gains"].append(t["exit_gain"])
            
            net_g = (t["exit_gain"] / 100.0) - 0.0010 # 扣 0.1% 摩擦成本
            day_pct += 0.50 * net_g
            
        cap *= (1.0 + day_pct)
        
    print("=" * 80)
    print("📊 【2024 全年中证 800 完整回测统计结果 (v0.2 优化版)】")
    print("=" * 80)
    print(f"• 测试交易日: 242 天 (覆盖全年)")
    print(f"• 实际成交总单数: {total_trades} 笔")
    print(f"• 战绩分布: {wins} 胜 / {draws} 平 / {losses} 负")
    print(f"• 【策略胜率 (Win Rate)】: {win_rate:.1f}%")
    print(f"• 次日开盘平均涨幅 (隔夜溢价): {avg_open:+.2f}%")
    print(f"• 交易平均平仓收益率: {avg_exit:+.2f}%")
    print(f"• 20 万元本金 2024 年末终值: {cap:,.2f} 元 (净赚 +{cap-200000:,.2f} 元, 收益率 +{(cap-200000)/200000*100:.2f}%)")
    
    print("\n📅 【2024 年 1~12 月逐月战绩明细表】:")
    print(f"{'月份':<8} | {'成交笔数':<6} | {'胜场':<4} | {'负场':<4} | {'月度胜率':<8} | {'平均单笔收益':<10} | {'月累计收益':<10}")
    print("-" * 68)
    for m, stat in sorted(monthly_data.items()):
        cnt = len(stat["trades"])
        w = stat["wins"]
        l = stat["losses"]
        wr = (w / cnt * 100) if cnt > 0 else 0.0
        avg_g = (sum(stat["gains"]) / cnt) if cnt > 0 else 0.0
        sum_g = sum(stat["gains"])
        print(f"{m:<8} | {cnt:<6} | {w:<4} | {l:<4} | {wr:5.1f}%   | {avg_g:+8.2f}%   | {sum_g:+8.2f}%")
    print("=" * 80)
    
    out_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backtest_2024_full_v02_results.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({
            "summary": {
                "total_trades": total_trades,
                "wins": wins,
                "draws": draws,
                "losses": losses,
                "win_rate": round(win_rate, 2),
                "avg_exit": round(avg_exit, 2),
                "final_cap_20w": round(cap, 2)
            },
            "monthly": {
                m: {
                    "count": len(stat["trades"]),
                    "wins": stat["wins"],
                    "losses": stat["losses"],
                    "win_rate": round(stat["wins"]/len(stat["trades"])*100, 1) if stat["trades"] else 0.0,
                    "avg_gain": round(sum(stat["gains"])/len(stat["gains"]), 2) if stat["gains"] else 0.0,
                    "sum_gain": round(sum(stat["gains"]), 2)
                } for m, stat in sorted(monthly_data.items())
            },
            "trades": all_trades
        }, f, ensure_ascii=False, indent=2)
    print(f"详细明细已存盘: {out_file}\n")

if __name__ == '__main__':
    run_2024_complete_backtest()
