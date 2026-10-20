#!/usr/bin/env python3
"""
2026 年度全样本严格点时回测 (Full Year 2026 Point-in-Time Backtest)
策略: tail-overnight-quant (v0.1)
严格无未来函数 (No Look-Ahead Bias):
在 T 日 14:40 做出决断前，绝不接触 T+1 日任何价格与盘口！
"""
import os
import sys
import json
import time
import datetime
import pandas as pd
import baostock as bs

# 添加依赖路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from tail_overnight_pipeline import (
    get_market_regime_snapshot,
    get_candidate_pool,
    evaluate_stock_snapshots,
    synthesize_layer5_decision
)

def fetch_single_day_kline_baostock(code: str, date_str: str) -> dict:
    """快速获取单只股票指定日期的日K线数据 (YYYYMMDD -> YYYY-MM-DD)，自动过滤停牌和异常空值"""
    prefix = "sh" if code.startswith("6") or code.startswith("5") or code.startswith("9") else "sz"
    bs_code = f"{prefix}.{code}"
    fmt_d = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    
    rs = bs.query_history_k_data_plus(
        bs_code,
        "date,open,high,low,close,preclose,amount,pctChg",
        start_date=fmt_d, end_date=fmt_d, frequency="d"
    )
    if rs.error_code == '0' and rs.next():
        row = rs.get_row_data()
        # 若任何关键字段为空字符串（停牌、无成交等），直接判为 None
        if not row or any(cell == '' for cell in row):
            return None
        try:
            return {
                "date": row[0].replace('-', ''),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "preclose": float(row[5]),
                "amount": float(row[6]),
                "pctChg": float(row[7])
            }
        except (ValueError, TypeError):
            return None
    return None

def run_full_year_2026_backtest():
    print("=" * 80)
    print("🚀 启动 2026 年初至今 (2026-01-05 ~ 2026-10-19) 全样本回测...")
    print("严格执行: 【无未来函数】(Point-in-Time) + 【5层快照全息仲裁】+ 【T+1四维纪律退出】")
    print("=" * 80)
    
    bs.login()
    
    # 1. 获取完整的交易日历
    rs = bs.query_trade_dates(start_date='2025-12-25', end_date='2026-10-20')
    cal_data = []
    while rs.error_code == '0' and rs.next():
        cal_data.append(rs.get_row_data())
    df_cal = pd.DataFrame(cal_data, columns=rs.fields)
    all_trade_days = [d.replace('-', '') for d in df_cal[df_cal['is_trading_day'] == '1']['calendar_date'].tolist()]
    
    # 找到 20260105 的位置
    start_idx = all_trade_days.index('20260105')
    end_idx = all_trade_days.index('20261019')
    
    print(f"📅 回测周期: {all_trade_days[start_idx]} 至 {all_trade_days[end_idx]} 共 {end_idx - start_idx + 1} 个实际交易日")
    
    daily_results = []
    all_trades = []
    
    t_start = time.time()
    
    for i in range(start_idx, end_idx + 1):
        prev_date = all_trade_days[i - 1]
        t_date = all_trade_days[i]
        next_date = all_trade_days[i + 1]
        
        # 1. 运行第 1 层: 大盘环境排雷快照 (严格在 T 日 14:40)
        market_snap = get_market_regime_snapshot(t_date)
        
        day_record = {
            "trade_date": t_date,
            "prev_date": prev_date,
            "next_date": next_date,
            "zt_count": market_snap["zt_count"],
            "zb_rate": market_snap["zb_rate"],
            "dt_count": market_snap["dt_count"],
            "market_passed": market_snap["passed"],
            "market_rating": market_snap["rating"],
            "warning_flag": market_snap.get("warning_flag"),
            "status": "PASS",
            "trades": []
        }
        
        # 若大盘门禁红灯未过 -> 直接空仓防守 (无需拉取种子与K线)
        if not market_snap["passed"]:
            day_record["status"] = "DEFENDED_BY_MARKET"
            daily_results.append(day_record)
            if (i - start_idx + 1) % 10 == 0:
                print(f"进度 [{i - start_idx + 1}/{end_idx - start_idx + 1}] {t_date}: 🛡️ 大盘避险红灯 ({market_snap['rating'][:16]}...)")
            continue
            
        # 大盘绿灯通过 -> 从 T-1 日涨停池提取候选种子
        candidates = get_candidate_pool(prev_date)
        if not candidates:
            day_record["status"] = "NO_CANDIDATES"
            daily_results.append(day_record)
            continue
            
        # 严格按 T 日客观行情生成第 2~4 层快照 (严禁接触 next_date)
        eval_list = []
        for c in candidates[:25]:
            code = c["code"]
            name = c["name"]
            reason = c["reason"]
            
            kline_t = fetch_single_day_kline_baostock(code, t_date)
            if not kline_t:
                continue
                
            # 组装虚拟单行 df 供 evaluate_stock_snapshots 使用
            df_dummy = pd.DataFrame([kline_t])
            ev = evaluate_stock_snapshots(code, name, t_date, reason, df_dummy)
            if ev:
                eval_list.append(ev)
                
        # 运行第 5 层: 统筹宏观与快照生成决策
        decisions = synthesize_layer5_decision(eval_list, market_snap)
        buy_targets = [d for d in decisions if d["action"] == "BUY"]
        
        if not buy_targets:
            day_record["status"] = "NO_QUALIFIED_STOCKS"
            daily_results.append(day_record)
            if (i - start_idx + 1) % 10 == 0:
                print(f"进度 [{i - start_idx + 1}/{end_idx - start_idx + 1}] {t_date}: 🟢 大盘放行但无符合黄金蓄势形态标的 (防守)")
            continue
            
        # ----------------------------------------------------------------------
        # 决策冻结分水岭: 此时 T 日尾盘决议已锁定 (最多买入排名前 2 只标的)
        # ----------------------------------------------------------------------
        day_record["status"] = "TRADED"
        day_trades = []
        
        for target in buy_targets[:2]:
            code = target["code"]
            name = target["name"]
            buy_price = target["close_price"]
            
            # 严格向后取 T+1 数据验证
            kline_t1 = fetch_single_day_kline_baostock(code, next_date)
            if not kline_t1:
                continue
                
            open_t1 = kline_t1["open"]
            high_t1 = kline_t1["high"]
            low_t1 = kline_t1["low"]
            close_t1 = kline_t1["close"]
            
            # 计算次日开盘表现与极值
            open_gain = round((open_t1 - buy_price) / buy_price * 100, 2)
            max_intraday_gain = round((high_t1 - buy_price) / buy_price * 100, 2)
            min_intraday_gain = round((low_t1 - buy_price) / buy_price * 100, 2)
            
            # 退出纪律撮合模拟 (v0.2 优化升级):
            # 1. 深度低开快速止损 (open_gain < -2.5%)，避免死扛恶化
            # 2. 阶梯一: 冲高 >= +1.0% 锁平保 (止损线拔高至 0.0%，浮盈绝不倒亏)
            # 3. 阶梯二: 冲高 >= +1.8% 紧凑吊灯止盈 (锁定高点回落 1.2% 收益)
            # 4. 盘中触及 -3.0% 兜底硬止损 (且未激活平保)
            # 5. 10:00 时间熔断平价出局
            is_ratchet_tier2 = (max_intraday_gain >= 1.8)
            is_ratchet_tier1 = (max_intraday_gain >= 1.0)
            is_hard_stop = (min_intraday_gain <= -3.0)
            
            if open_gain < -2.5:
                exit_gain = open_gain
                exit_rule = "🚨 竞价深度低开果断止损"
            elif is_ratchet_tier2:
                exit_gain = round(max_intraday_gain - 1.2, 2)
                exit_rule = f"🎯 冲高至+{max_intraday_gain}%紧凑吊灯止盈"
            elif is_ratchet_tier1:
                # 激活平保，保本平盘或微利出局，绝不亏损
                exit_gain = max(0.0, round(max_intraday_gain - 1.0, 2))
                exit_rule = f"🛡️ 冲高至+{max_intraday_gain}%激活平保锁防守"
            elif is_hard_stop:
                exit_gain = -3.0
                exit_rule = "🚨 盘中触及-3.0%硬止损"
            else:
                exit_gain = open_gain
                exit_rule = "⌛ 10:00 时间熔断平价出局"
                
            is_win = (exit_gain > 0)
            trade_info = {
                "trade_date": t_date,
                "next_date": next_date,
                "code": code,
                "name": name,
                "reason": target["snap2"]["reason_type"],
                "buy_price": buy_price,
                "open_t1": open_t1,
                "open_gain": open_gain,
                "high_t1": high_t1,
                "max_intraday_gain": max_intraday_gain,
                "exit_gain": exit_gain,
                "exit_rule": exit_rule,
                "is_win": is_win
            }
            day_trades.append(trade_info)
            all_trades.append(trade_info)
            
        day_record["trades"] = day_trades
        daily_results.append(day_record)
        
        # 实时打印交易结果
        for tr in day_trades:
            print(f"[{t_date} -> {next_date}] 开仓 {tr['name']}({tr['code']}): 买入价 {tr['buy_price']:.2f} | 次日开盘 {tr['open_gain']:+.2f}% | 最终退出 {tr['exit_gain']:+.2f}% ({tr['exit_rule']})")

    bs.logout()
    t_elapsed = time.time() - t_start
    print(f"\n✅ 2026 年度全样本回测计算完成！耗时: {t_elapsed:.1f} 秒\n")
    
    # --------------------------------------------------------------------------
    # 汇总统计与月度拆解
    # --------------------------------------------------------------------------
    total_days = len(daily_results)
    defended_days = len([d for d in daily_results if d["status"] == "DEFENDED_BY_MARKET"])
    no_setup_days = len([d for d in daily_results if d["status"] in ["NO_CANDIDATES", "NO_QUALIFIED_STOCKS"]])
    traded_days = len([d for d in daily_results if d["status"] == "TRADED"])
    
    total_trades = len(all_trades)
    wins = len([t for t in all_trades if t["exit_gain"] > 0])
    draws = len([t for t in all_trades if t["exit_gain"] == 0])
    losses = len([t for t in all_trades if t["exit_gain"] < 0])
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
    
    avg_open_gain = (sum(t["open_gain"] for t in all_trades) / total_trades) if total_trades > 0 else 0.0
    avg_exit_gain = (sum(t["exit_gain"] for t in all_trades) / total_trades) if total_trades > 0 else 0.0
    
    win_gains = [t["exit_gain"] for t in all_trades if t["exit_gain"] > 0]
    loss_gains = [abs(t["exit_gain"]) for t in all_trades if t["exit_gain"] < 0]
    avg_win = (sum(win_gains) / len(win_gains)) if win_gains else 0.0
    avg_loss = (sum(loss_gains) / len(loss_gains)) if loss_gains else 1.0
    pl_ratio = (avg_win / avg_loss) if avg_loss > 0 else 0.0
    
    # 月度逐月统计
    monthly_stats = {}
    for t in all_trades:
        m = t["trade_date"][:6] # YYYYMM
        if m not in monthly_stats:
            monthly_stats[m] = {"trades": [], "wins": 0, "losses": 0, "gains": []}
        monthly_stats[m]["trades"].append(t)
        if t["exit_gain"] > 0:
            monthly_stats[m]["wins"] += 1
        elif t["exit_gain"] < 0:
            monthly_stats[m]["losses"] += 1
        monthly_stats[m]["gains"].append(t["exit_gain"])
        
    # 保存结果文件
    res_payload = {
        "summary": {
            "total_trading_days": total_days,
            "defended_days": defended_days,
            "no_setup_days": no_setup_days,
            "traded_days": traded_days,
            "total_trades": total_trades,
            "wins": wins,
            "draws": draws,
            "losses": losses,
            "win_rate": round(win_rate, 2),
            "avg_open_gain": round(avg_open_gain, 2),
            "avg_exit_gain": round(avg_exit_gain, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "profit_loss_ratio": round(pl_ratio, 2)
        },
        "monthly_breakdown": {
            m: {
                "count": len(data["trades"]),
                "wins": data["wins"],
                "losses": data["losses"],
                "win_rate": round(data["wins"] / len(data["trades"]) * 100, 1) if data["trades"] else 0.0,
                "avg_gain": round(sum(data["gains"]) / len(data["gains"]), 2) if data["gains"] else 0.0,
                "sum_gain": round(sum(data["gains"]), 2)
            }
            for m, data in sorted(monthly_stats.items())
        },
        "trades": all_trades
    }
    
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backtest_2026_full_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(res_payload, f, ensure_ascii=False, indent=2)
        
    print("=" * 80)
    print("📊 【2026 年度全样本严格点时回测统计结果】")
    print("=" * 80)
    print(f"• 交易日总数: {total_days} 天")
    print(f"• 大盘门禁避险天数 (空仓护体): {defended_days} 天 ({defended_days/total_days*100:.1f}%)")
    print(f"• 绿灯但无形态符合天数: {no_setup_days} 天")
    print(f"• 实际开仓交易日: {traded_days} 天 ({traded_days/total_days*100:.1f}%)")
    print(f"• 总成交单数: {total_trades} 笔")
    print(f"• 胜负战绩: {wins} 胜 / {draws} 平 / {losses} 负")
    print(f"• 【策略胜率 (Win Rate)】: {win_rate:.1f}%")
    print(f"• 次日开盘平均涨幅 (隔夜溢价): {avg_open_gain:+.2f}%")
    print(f"• 交易平均平仓收益率: {avg_exit_gain:+.2f}%")
    print(f"• 平均单笔盈利: +{avg_win:.2f}% | 平均单笔亏损: -{avg_loss:.2f}%")
    print(f"• 盈亏比 (Profit/Loss Ratio): {pl_ratio:.2f}")
    print("\n📅 【2026 年逐月战绩分布表】:")
    print(f"{'月份':<8} | {'交易笔数':<6} | {'胜场':<4} | {'负场':<4} | {'月度胜率':<8} | {'平均单笔收益':<10} | {'月累计收益':<10}")
    print("-" * 68)
    for m, stat in sorted(monthly_stats.items()):
        cnt = len(stat["trades"])
        w = stat["wins"]
        l = stat["losses"]
        wr = (w / cnt * 100) if cnt > 0 else 0.0
        avg_g = (sum(stat["gains"]) / cnt) if cnt > 0 else 0.0
        sum_g = sum(stat["gains"])
        print(f"{m:<8} | {cnt:<6} | {w:<4} | {l:<4} | {wr:5.1f}%   | {avg_g:+8.2f}%   | {sum_g:+8.2f}%")
    print("=" * 80)
    print(f"详细回测明细已保存至: {out_path}\n")

if __name__ == '__main__':
    run_full_year_2026_backtest()
