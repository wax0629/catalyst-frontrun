#!/usr/bin/env python3
"""
2025 年 Q4 样本外严格点时回测 (Out-of-sample Backtest for 2025 Q4)
周期: 2025-10-10 至 2025-12-31 (60个交易日)
目标: 检验 2026 年发现的胜率瓶颈与规律在 2025 年末是否完全一致重现！
"""
import os
import sys
import json
import time
import pandas as pd
import baostock as bs

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".agents/skills/tail-overnight-quant/scripts"))
from tail_overnight_pipeline import (
    get_market_regime_snapshot,
    get_candidate_pool,
    evaluate_stock_snapshots,
    synthesize_layer5_decision
)
from full_year_backtest import fetch_single_day_kline_baostock

def run_2025_q4_backtest():
    print("=" * 80)
    print("🚀 启动 2025 年 Q4 严格点时样本外回测 (2025-10-10 ~ 2025-12-31)...")
    print("=" * 80)
    
    bs.login()
    rs = bs.query_trade_dates(start_date='2025-10-08', end_date='2026-01-06')
    cal_data = []
    while rs.error_code == '0' and rs.next():
        cal_data.append(rs.get_row_data())
    df_cal = pd.DataFrame(cal_data, columns=rs.fields)
    all_trade_days = [d.replace('-', '') for d in df_cal[df_cal['is_trading_day'] == '1']['calendar_date'].tolist()]
    
    start_idx = all_trade_days.index('20251010')
    end_idx = all_trade_days.index('20251231')
    
    daily_results = []
    all_trades = []
    
    for i in range(start_idx, end_idx + 1):
        prev_date = all_trade_days[i - 1]
        t_date = all_trade_days[i]
        next_date = all_trade_days[i + 1]
        
        market_snap = get_market_regime_snapshot(t_date)
        if not market_snap["passed"]:
            daily_results.append({"trade_date": t_date, "status": "DEFENDED_BY_MARKET"})
            continue
            
        candidates = get_candidate_pool(prev_date)
        if not candidates:
            daily_results.append({"trade_date": t_date, "status": "NO_CANDIDATES"})
            continue
            
        eval_list = []
        for c in candidates[:25]:
            code = c["code"]
            name = c["name"]
            reason = c["reason"]
            
            kline_t = fetch_single_day_kline_baostock(code, t_date)
            if not kline_t:
                continue
            df_dummy = pd.DataFrame([kline_t])
            ev = evaluate_stock_snapshots(code, name, t_date, reason, df_dummy)
            if ev:
                eval_list.append(ev)
                
        decisions = synthesize_layer5_decision(eval_list, market_snap)
        buy_targets = [d for d in decisions if d["action"] == "BUY"]
        
        if not buy_targets:
            daily_results.append({"trade_date": t_date, "status": "NO_QUALIFIED_STOCKS"})
            continue
            
        # 冻结决策，向后取 T+1 数据
        for target in buy_targets[:2]:
            code = target["code"]
            name = target["name"]
            buy_price = target["close_price"]
            
            kline_t1 = fetch_single_day_kline_baostock(code, next_date)
            if not kline_t1:
                continue
                
            open_t1 = kline_t1["open"]
            high_t1 = kline_t1["high"]
            low_t1 = kline_t1["low"]
            close_t1 = kline_t1["close"]
            
            open_gain = round((open_t1 - buy_price) / buy_price * 100, 2)
            max_intraday_gain = round((high_t1 - buy_price) / buy_price * 100, 2)
            min_intraday_gain = round((low_t1 - buy_price) / buy_price * 100, 2)
            
            is_ratchet = (max_intraday_gain >= 2.0)
            is_hard_stop = (min_intraday_gain <= -3.0)
            
            if open_gain < -3.0:
                exit_gain = open_gain
                exit_rule = "🚨 开盘深度低开止损"
            elif is_hard_stop and not is_ratchet:
                exit_gain = -3.0
                exit_rule = "🚨 盘中触及-3.0%硬止损"
            elif is_ratchet:
                exit_gain = round(max_intraday_gain - 1.5, 2)
                exit_rule = f"🎯 冲高至+{max_intraday_gain}%吊灯止盈"
            else:
                exit_gain = open_gain
                exit_rule = "⌛ 10:00 时间熔断平价出局"
                
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
                "is_win": (exit_gain > 0)
            }
            all_trades.append(trade_info)
            print(f"[{t_date} -> {next_date}] {name}({code}): 买入={buy_price:.2f} | 次日开盘={open_gain:+.2f}% | 最终退出={exit_gain:+.2f}% ({exit_rule})")
            
    bs.logout()
    
    # 统计
    total_trades = len(all_trades)
    wins = len([t for t in all_trades if t["exit_gain"] > 0])
    draws = len([t for t in all_trades if t["exit_gain"] == 0])
    losses = len([t for t in all_trades if t["exit_gain"] < 0])
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
    
    print("\n" + "=" * 80)
    print("📊 【2025 年 Q4 样本外回测结果】")
    print("=" * 80)
    print(f"• 总成交单数: {total_trades} 笔")
    print(f"• 胜/平/负: {wins} 胜 / {draws} 平 / {losses} 负")
    print(f"• 【策略胜率 (Win Rate)】: {win_rate:.1f}%")
    print(f"• 平均单笔平仓收益率: {sum(t['exit_gain'] for t in all_trades)/total_trades:+.2f}%")
    
    # 分析亏损单中有多少冲高
    losses_list = [t for t in all_trades if t["exit_gain"] < 0]
    surged_losses = [t for t in losses_list if t["max_intraday_gain"] >= 1.0]
    print(f"• 亏损单中早盘冲高 >= +1.0% 的占比: {len(surged_losses)}/{len(losses_list)} ({len(surged_losses)/len(losses_list)*100:.1f}%)")
    for s in surged_losses:
        print(f"  - {s['name']}({s['code']}) on {s['trade_date']}: 盘中最高冲至 {s['max_intraday_gain']:+.2f}%, 最终由于未触及+2.0%回落止损 {s['exit_gain']:+.2f}%")
        
    out_f = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backtest_2025_q4_results.json")
    with open(out_f, "w", encoding="utf-8") as f:
        json.dump(all_trades, f, ensure_ascii=False, indent=2)

if __name__ == '__main__':
    run_2025_q4_backtest()
