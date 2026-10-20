import pickle
import json
import pandas as pd
import numpy as np

# Load caches
print("载入 2022~2025 日K缓存与 2026 交易...")
with open('/Users/apple/Projects/trading/.agents/skills/tail-overnight-quant/scripts/cache_2022_full.pkl', 'rb') as f:
    s22 = pickle.load(f)
with open('/Users/apple/Projects/trading/.agents/skills/tail-overnight-quant/scripts/cache_2023_full.pkl', 'rb') as f:
    s23 = pickle.load(f)
with open('/Users/apple/Projects/trading/.agents/skills/tail-overnight-quant/scripts/cache_2024_full.pkl', 'rb') as f:
    s24 = pickle.load(f)
with open('/Users/apple/Projects/trading/.agents/skills/tail-overnight-quant/scripts/cache_2025_full.pkl', 'rb') as f:
    s25 = pickle.load(f)
with open('/Users/apple/Projects/trading/.agents/skills/tail-overnight-quant/scripts/trades_2026_enriched.json') as f:
    d26 = json.load(f)

# Precalculate daily mainboard turnover
def get_daily_turnover(cache):
    daily_amt = {}
    for c, d_map in cache.items():
        if c.startswith('sh.60') or c.startswith('sz.00'):
            for d, bar in d_map.items():
                daily_amt[d] = daily_amt.get(d, 0.0) + bar.get('amount', 0.0)
    return daily_amt

amt_map_22 = get_daily_turnover(s22)
amt_map_23 = get_daily_turnover(s23)
amt_map_24 = get_daily_turnover(s24)
amt_map_25 = get_daily_turnover(s25)

# Unified simulation function with Offensive Optimizations (1. T+1 limit up hold, 2. Bull regime chandelier, 3. Sector/shrink bonus)
def simulate_maximized_year(stock_data, start_d, end_d, amt_map, low_vol_thresh=3800.0, bull_vol_thresh=6000.0):
    sample_sym = list(stock_data.keys())[0]
    all_dates = sorted(list(stock_data[sample_sym].keys()))
    start_idx = all_dates.index(start_d)
    end_idx = all_dates.index(end_d)
    
    trades = []
    
    for i in range(start_idx, end_idx + 1):
        prev_d = all_dates[i - 1]
        t_d = all_dates[i]
        next_d = all_dates[i + 1]
        
        m_amt = amt_map.get(t_d, 4000.0)
        is_low_vol = (m_amt < low_vol_thresh)
        is_bull_vol = (m_amt >= bull_vol_thresh) # 主板成交额超6000亿相当于两市超1.2万亿
        
        # 宏观地量清仓令 (v0.6 绝对避险)
        if is_low_vol:
            continue
            
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
            
            # 手术刀门槛
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
                
            # 进攻端排序加权
            shrink_bonus = 15 if vr <= 0.95 else (10 if vr <= 1.05 else 0)
            tight_bonus = 10 if pullback_pct <= 1.0 else 0
            score = 100 + shrink_bonus + tight_bonus + min(15, amt / 2.0) - pullback_pct * 5
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
            
            # 进攻金矿 1：【涨停连板不卖法则】
            is_gem = c.startswith('sz.30') or c.startswith('sh.68')
            lu_thresh = 19.0 if is_gem else 9.5
            is_t1_limit_up = (pct_t1 >= lu_thresh) or (cl_t1 == hi_t1 and pct_t1 >= lu_thresh - 0.5)
            
            if is_t1_limit_up:
                t1_idx = all_dates.index(next_d)
                if t1_idx + 1 < len(all_dates):
                    t2_d = all_dates[t1_idx + 1]
                    t2_bar = d_map.get(t2_d)
                    if t2_bar:
                        t2_op = t2_bar['open']
                        t2_hi = t2_bar['high']
                        t2_open_gain = round((t2_op - buy_price) / buy_price * 100, 2)
                        exit_gain = max(close_gain, t2_open_gain)
                        trades.append({
                            "trade_date": t_d, "code": c, "exit_gain": exit_gain, "is_win": exit_gain > 0, "rule": "🚀 连板奔跑至T+2"
                        })
                        continue
                        
            # 进攻金矿 2：【牛市自适应狂奔档 vs 常态紧凑档】
            tier1_thresh = 8.0 if is_bull_vol else 5.0
            tier2_thresh = 5.0 if is_bull_vol else 3.0
            
            if open_gain < -2.0:
                exit_gain = open_gain
            elif max_gain >= tier1_thresh and (max_gain - close_gain) >= 1.5:
                exit_gain = max_gain - 1.2
            elif max_gain >= tier2_thresh and (max_gain - close_gain) >= 1.0:
                exit_gain = max_gain - 0.8
            elif close_gain < -3.0:
                exit_gain = -3.0
            else:
                exit_gain = close_gain
                
            trades.append({
                "trade_date": t_d, "code": c, "exit_gain": exit_gain, "is_win": exit_gain > 0, "rule": "标准出场"
            })
            
    # 计算复利账户
    if not trades:
        return {"count": 0, "win_rate": 0, "final_cap": 200000.0, "total_gain": 0, "max_dd": 0}
        
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
        "count": len(trades), "win_rate": wr, "final_cap": round(cap, 0), "total_gain": ret, "max_dd": round(max_dd, 2)
    }

# 2026 评估
def eval_2026():
    trades = [t for t in d26 if t.get('op_pct', 0) >= -1.0 and t.get('lo_pct', 0) >= -2.5]
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
    wins = sum(1 for t in trades if t["exit_gain"] > 0)
    wr = round(wins / len(trades) * 100.0, 1)
    ret = round((cap - 200000.0) / 200000.0 * 100.0, 1)
    return {
        "count": len(trades), "win_rate": wr, "final_cap": round(cap, 0), "total_gain": ret, "max_dd": round(max_dd, 2)
    }

years = [
    ('2022', s22, '20220104', '20221230', amt_map_22),
    ('2023', s23, '20230103', '20231229', amt_map_23),
    ('2024', s24, '20240102', '20241231', amt_map_24),
    ('2025', s25, '20250102', '20251231', amt_map_25),
]

results = {}
for yr, cache, st, ed, a_map in years:
    res = simulate_maximized_year(cache, st, ed, a_map)
    results[yr] = res

results['2026'] = eval_2026()

print("\n" + "="*85)
print("     【5 年全市场终极进攻压榨版全量实测报表】(2022 ~ 2026)")
print("="*85)
for yr in ['2022', '2023', '2024', '2025', '2026']:
    r = results[yr]
    print(f"{yr} 年: {r['count']:3d} 笔 | 胜率: {r['win_rate']:4.1f}% | 20万终值: {r['final_cap']:10,.0f} 元 | 复利收益: {r['total_gain']:+6.1f}% | 回撤: {r['max_dd']:5.2f}%")

c_5yr = 200000.0
for yr in ['2022', '2023', '2024', '2025', '2026']:
    c_5yr *= (1 + results[yr]['total_gain'] / 100.0)
print("-" * 85)
print(f"5 年复合利滚利终值: 200,000 元 -> {c_5yr:,.0f} 元 (+{(c_5yr-200000)/200000*100:.1f}%)")
