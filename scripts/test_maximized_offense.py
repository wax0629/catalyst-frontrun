import pickle
import json
import pandas as pd
import numpy as np

# Load caches
with open('/Users/apple/Projects/trading/.agents/skills/tail-overnight-quant/scripts/cache_2024_full.pkl', 'rb') as f:
    s24 = pickle.load(f)
with open('/Users/apple/Projects/trading/.agents/skills/tail-overnight-quant/scripts/cache_2025_full.pkl', 'rb') as f:
    s25 = pickle.load(f)

def run_maximized_simulation(stock_data, start_d, end_d, enable_limit_up_hold=True, enable_alpha_ranking=True):
    sample_sym = list(stock_data.keys())[0]
    all_dates = sorted(list(stock_data[sample_sym].keys()))
    start_idx = all_dates.index(start_d)
    end_idx = all_dates.index(end_d)
    
    trades = []
    
    for i in range(start_idx, end_idx + 1):
        prev_d = all_dates[i - 1]
        t_d = all_dates[i]
        next_d = all_dates[i + 1]
        
        candidates = []
        for c, d_map in stock_data.items():
            prev_bar = d_map.get(prev_d)
            if prev_bar and prev_bar["pctChg"] > 0:
                is_gem_star = c.startswith("sz.30") or c.startswith("sh.68")
                thresh = 19.2 if is_gem_star else 9.5
                if prev_bar["pctChg"] >= thresh:
                    candidates.append(c)
                    
        if not candidates:
            continue
            
        qualified = []
        for c in candidates:
            d_map = stock_data[c]
            t_bar = d_map.get(t_d)
            prev_bar = d_map.get(prev_d)
            if not t_bar or not prev_bar:
                continue
                
            amt = t_bar["amount"]
            pct = t_bar["pctChg"]
            hi = t_bar["high"]
            cl = t_bar["close"]
            op = t_bar["open"]
            lo = t_bar["low"]
            pre = t_bar["preclose"]
            prev_amt = prev_bar["amount"]
            
            if cl <= 0 or pre <= 0 or prev_amt <= 0:
                continue
                
            max_gain_pct = (hi - pre) / pre * 100 if pre > 0 else 0
            pullback_pct = (hi - cl) / hi * 100 if hi > 0 else 0
            open_pct = (op - pre) / pre * 100 if pre > 0 else 0
            lo_pct = (lo - pre) / pre * 100 if pre > 0 else 0
            vr = amt / prev_amt
            
            # Universal Surgical Filters
            if not (4.5 <= amt <= 14.0):
                continue
            if not (1.8 <= pct <= 5.0):
                continue
            if max_gain_pct >= 6.0 and pullback_pct >= 2.0:
                continue
            if pullback_pct > 2.0:
                continue
            if open_pct < -1.0:
                continue
            if lo_pct < -2.5:
                continue
            if vr > 1.30:
                continue
                
            # Alpha Ranking (进攻端极致排序)
            if enable_alpha_ranking:
                # 缩量极致洗盘优先 (vr <= 0.95 +15分, vr <= 1.05 +10分)
                shrink_bonus = 15 if vr <= 0.95 else (10 if vr <= 1.05 else 0)
                # 黄金蓄势紧凑回落优先 (pullback <= 1.0% +10分)
                tight_bonus = 10 if pullback_pct <= 1.0 else 0
                # 轻骑兵最佳流动性 (5.5~10亿 +10分)
                sweet_bonus = 10 if (5.5 <= amt <= 10.0) else 5
                score = 100 + shrink_bonus + tight_bonus + sweet_bonus - pullback_pct * 5
            else:
                score = 100 + min(20, amt / 2.0) - pullback_pct * 5
                
            qualified.append({"code": c, "close_price": cl, "score": score})
            
        if not qualified:
            continue
            
        qualified.sort(key=lambda x: x["score"], reverse=True)
        selected = qualified[:2]
        
        for s in selected:
            c = s["code"]
            buy_price = s["close_price"]
            d_map = stock_data[c]
            next_bar = d_map.get(next_d)
            if not next_bar:
                continue
                
            op_t1 = next_bar["open"]
            hi_t1 = next_bar["high"]
            cl_t1 = next_bar["close"]
            pct_t1 = next_bar["pctChg"]
            
            open_gain = round((op_t1 - buy_price) / buy_price * 100, 2)
            max_gain = round((hi_t1 - buy_price) / buy_price * 100, 2)
            close_gain = round((cl_t1 - buy_price) / buy_price * 100, 2)
            
            # Check T+1 Limit Up Holding (让涨停板利润奔跑)
            is_gem = c.startswith('sz.30') or c.startswith('sh.68')
            lu_thresh = 19.0 if is_gem else 9.5
            is_t1_limit_up = (pct_t1 >= lu_thresh) or (cl_t1 == hi_t1 and pct_t1 >= lu_thresh - 0.5)
            
            if enable_limit_up_hold and is_t1_limit_up:
                t1_idx = all_dates.index(next_d)
                if t1_idx + 1 < len(all_dates):
                    t2_d = all_dates[t1_idx + 1]
                    t2_bar = d_map.get(t2_d)
                    if t2_bar:
                        t2_op = t2_bar['open']
                        t2_hi = t2_bar['high']
                        t2_open_gain = round((t2_op - buy_price) / buy_price * 100, 2)
                        t2_max_gain = round((t2_hi - buy_price) / buy_price * 100, 2)
                        # T+2 exit
                        exit_gain = max(close_gain, t2_open_gain)
                        trades.append({
                            "trade_date": t_d, "code": c, "exit_gain": exit_gain, "is_win": exit_gain > 0, "rule": "🚀 连板奔跑持股到T+2"
                        })
                        continue
                        
            # Standard Exit Machine
            if open_gain < -2.0:
                exit_gain = open_gain
            elif max_gain >= 5.0 and (max_gain - close_gain) >= 1.5:
                exit_gain = max_gain - 1.2
            elif max_gain >= 3.0 and (max_gain - close_gain) >= 1.0:
                exit_gain = max_gain - 0.8
            elif close_gain < -3.0:
                exit_gain = -3.0
            else:
                exit_gain = close_gain
                
            trades.append({
                "trade_date": t_d, "code": c, "exit_gain": exit_gain, "is_win": exit_gain > 0, "rule": "标准出场"
            })
            
    if not trades:
        return {"count": 0, "win_rate": 0, "final_cap": 200000.0, "compound_ret": 0, "max_dd": 0}
        
    by_date = {}
    for t in trades:
        d = t["trade_date"]
        if d not in by_date: by_date[d] = []
        by_date[d].append(t)
        
    cap = 200000.0
    cap_curve = [cap]
    peak = cap
    max_dd = 0.0
    for d, d_trades in sorted(by_date.items()):
        sub_cap = cap / len(d_trades)
        day_pnl = sum(sub_cap * (t["exit_gain"] / 100.0) for t in d_trades)
        cap += day_pnl
        cap_curve.append(cap)
        if cap > peak: peak = cap
        dd = (peak - cap) / peak * 100.0
        if dd > max_dd: max_dd = dd
        
    wins = sum(1 for t in trades if t["is_win"])
    wr = round(wins / len(trades) * 100.0, 1)
    ret = round((cap - 200000.0) / 200000.0 * 100.0, 1)
    return {
        "count": len(trades), "win_rate": wr, "final_cap": round(cap, 0), "compound_ret": ret, "max_dd": round(max_dd, 2)
    }

print("=== 对比测试：基准防守版 vs 进攻压榨极致版 ===")
r24_base = run_maximized_simulation(s24, '20240102', '20241231', False, False)
r24_max = run_maximized_simulation(s24, '20240102', '20241231', True, True)

r25_base = run_maximized_simulation(s25, '20250102', '20251231', False, False)
r25_max = run_maximized_simulation(s25, '20250102', '20251231', True, True)

print(f"2024 基准: {r24_base['count']}笔 | 胜率: {r24_base['win_rate']}% | 终值: {r24_base['final_cap']:9,.0f} 元 (+{r24_base['compound_ret']}%) | 回撤: {r24_base['max_dd']}%")
print(f"2024 压榨: {r24_max['count']}笔 | 胜率: {r24_max['win_rate']}% | 终值: {r24_max['final_cap']:9,.0f} 元 (+{r24_max['compound_ret']}%) | 回撤: {r24_max['max_dd']}%")

print(f"2025 基准: {r25_base['count']}笔 | 胜率: {r25_base['win_rate']}% | 终值: {r25_base['final_cap']:9,.0f} 元 (+{r25_base['compound_ret']}%) | 回撤: {r25_base['max_dd']}%")
print(f"2025 压榨: {r25_max['count']}笔 | 胜率: {r25_max['win_rate']}% | 终值: {r25_max['final_cap']:9,.0f} 元 (+{r25_max['compound_ret']}%) | 回撤: {r25_max['max_dd']}%")
