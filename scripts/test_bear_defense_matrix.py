import pickle
import json
import pandas as pd
import numpy as np

# Load CSI 300
df_csi = pd.read_csv('/Users/apple/Projects/trading/.agents/skills/tail-overnight-quant/scripts/csi300_daily.csv')
csi_map = {}
for _, row in df_csi.iterrows():
    csi_map[str(int(row['date']))] = {
        'close': float(row['close']),
        'ma5': float(row['ma5']),
        'above_ma5': float(row['close']) >= float(row['ma5'])
    }

def run_simulation(stock_data, start_date, end_date, config):
    sample_sym = list(stock_data.keys())[0]
    all_dates = sorted(list(stock_data[sample_sym].keys()))
    
    start_idx = all_dates.index(start_date)
    end_idx = all_dates.index(end_date)
    
    trades = []
    
    for i in range(start_idx, end_idx + 1):
        prev_d = all_dates[i - 1]
        t_d = all_dates[i]
        next_d = all_dates[i + 1]
        
        # Check CSI 300 status on T-day
        csi_info = csi_map.get(t_d, {'above_ma5': True})
        is_above_ma5 = csi_info['above_ma5']
        
        # Macro MA5 hard block rule
        if config.get('ma5_hard_block') and not is_above_ma5:
            continue
            
        # Determine position sizing factor
        if config.get('dynamic_sizing') and not is_above_ma5:
            pos_weight = 0.5 # 半仓防守
        else:
            pos_weight = 1.0 # 满仓运作
            
        # 1. T-1 Limit-up seeds
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
            
            # Volume ratio (量比)
            vr = amt / prev_amt
            
            # Universal Micro-Filters (Surgical clean)
            if amt < config.get('min_amt', 4.0):
                continue
            if config.get('max_amt') and amt > config['max_amt']:
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
                
            # Volume Ratio Filter (缩量蓄势 vs 放量滞涨)
            if config.get('max_vr') and vr > config['max_vr']:
                continue
                
            # Scoring
            # If volume_smart scoring is enabled: penalize overly bulky stocks in bear, reward sweet spot
            if config.get('smart_volume_scoring'):
                # Sweet spot 5.5 ~ 10.0 亿 gets highest score
                liquidity_score = 15 if (5.5 <= amt <= 10.0) else (10 if amt < 5.5 else 5)
                # Shrink volume bonus: vr <= 1.0 gets bonus
                shrink_bonus = 10 if vr <= 1.05 else 0
                score = 100 + liquidity_score + shrink_bonus - pullback_pct * 5
            else:
                score = 100 + min(20, amt / 2.0) - pullback_pct * 5
                
            qualified.append({
                "code": c,
                "close_price": cl,
                "score": score,
                "amt": amt,
                "vr": vr
            })
            
        if not qualified:
            continue
            
        qualified.sort(key=lambda x: x["score"], reverse=True)
        selected = qualified[:2]
        
        for s in selected:
            c = s["code"]
            buy_price = s["close_price"]
            next_bar = stock_data[c].get(next_d)
            if not next_bar:
                continue
                
            op_t1 = next_bar["open"]
            hi_t1 = next_bar["high"]
            lo_t1 = next_bar["low"]
            cl_t1 = next_bar["close"]
            
            open_gain = round((op_t1 - buy_price) / buy_price * 100, 2)
            max_gain = round((hi_t1 - buy_price) / buy_price * 100, 2)
            close_gain = round((cl_t1 - buy_price) / buy_price * 100, 2)
            
            if open_gain < -2.0:
                exit_gain = open_gain
                rule = "🚨 竞价深度低开果断止损"
            elif max_gain >= 5.0 and (max_gain - close_gain) >= 1.5:
                exit_gain = max_gain - 1.2
                rule = "🎯 冲高至+5%以上紧凑吊灯止盈"
            elif max_gain >= 3.0 and (max_gain - close_gain) >= 1.0:
                exit_gain = max_gain - 0.8
                rule = "🎯 冲高至+3%以上适度止盈"
            elif close_gain < -3.0:
                exit_gain = -3.0
                rule = "🛑 尾盘保命止损"
            else:
                exit_gain = close_gain
                rule = "平价出场"
                
            # Apply dynamic position weighting
            weighted_gain = exit_gain * pos_weight
            
            trades.append({
                "trade_date": t_d,
                "next_date": next_d,
                "code": c,
                "exit_gain": exit_gain,
                "pos_weight": pos_weight,
                "weighted_gain": weighted_gain,
                "is_win": exit_gain > 0,
                "above_ma5": is_above_ma5,
                "amt": s["amt"],
                "vr": s["vr"]
            })
            
    if not trades:
        return {"count": 0, "win_rate": 0, "avg_gain": 0, "total_compound": 0, "max_dd": 0}
        
    cap = 200000.0
    cap_curve = [cap]
    for t in trades:
        # Each trade risks 50% of capital at pos_weight=1.0, or 25% of capital at pos_weight=0.5
        # Since we buy up to 2 stocks per day, each stock takes half the available capital
        trade_cap = (cap * 0.5) * t["pos_weight"]
        pnl = trade_cap * (t["exit_gain"] / 100.0)
        cap += pnl
        cap_curve.append(cap)
        
    peak = cap_curve[0]
    max_dd = 0.0
    for v in cap_curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak * 100.0
        if dd > max_dd:
            max_dd = dd
            
    win_cnt = sum(1 for t in trades if t["is_win"])
    win_rate = win_cnt / len(trades) * 100.0
    avg_gain = sum(t["exit_gain"] for t in trades) / len(trades)
    total_ret = (cap - 200000.0) / 200000.0 * 100.0
    
    return {
        "count": len(trades),
        "win_rate": round(win_rate, 1),
        "avg_gain": round(avg_gain, 2),
        "total_compound": round(total_ret, 1),
        "final_cap": round(cap, 2),
        "max_dd": round(max_dd, 1),
        "trades": trades
    }

if __name__ == '__main__':
    print("Script ready.")

# Load caches
print("Loading 2023, 2024, 2025 caches...")
with open('/Users/apple/Projects/trading/.agents/skills/tail-overnight-quant/scripts/cache_2023_full.pkl', 'rb') as f:
    s23 = pickle.load(f)
with open('/Users/apple/Projects/trading/.agents/skills/tail-overnight-quant/scripts/cache_2024_full.pkl', 'rb') as f:
    s24 = pickle.load(f)
with open('/Users/apple/Projects/trading/.agents/skills/tail-overnight-quant/scripts/cache_2025_full.pkl', 'rb') as f:
    s25 = pickle.load(f)

configs = {
    "1. 纯净基准(无MA5无成交量约束)": {
        "min_amt": 4.0,
        "ma5_hard_block": False,
        "dynamic_sizing": False,
        "smart_volume_scoring": False
    },
    "2. 宏观MA5硬闸门(跌破MA5完全空仓)": {
        "min_amt": 4.0,
        "ma5_hard_block": True,
        "dynamic_sizing": False,
        "smart_volume_scoring": False
    },
    "3. 纯量价体系(成交量黄金带5-12亿+缩量蓄势优先,无MA5)": {
        "min_amt": 5.0,
        "max_amt": 14.0,
        "max_vr": 1.25,
        "ma5_hard_block": False,
        "dynamic_sizing": False,
        "smart_volume_scoring": True
    },
    "4. 柔性全能防御(量价黄金带+弱势半仓防守Dynamic Sizing)": {
        "min_amt": 4.5,
        "max_amt": 15.0,
        "max_vr": 1.30,
        "ma5_hard_block": False,
        "dynamic_sizing": True, # 线下半仓，线上满仓
        "smart_volume_scoring": True
    }
}

years = [
    ("2023 (大熊市样本外)", s23, '20230103', '20231229'),
    ("2024 (暴跌与V型反弹)", s24, '20240102', '20241231'),
    ("2025 (牛市大分化)", s25, '20250102', '20251231'),
]

for cfg_name, cfg in configs.items():
    print(f"\n==========================================")
    print(f"模式: {cfg_name}")
    print(f"==========================================")
    for y_name, data, st, ed in years:
        res = run_simulation(data, st, ed, cfg)
        print(f"{y_name:20s} | 交易: {res['count']:3d}笔 | 胜率: {res['win_rate']:4.1f}% | 均利: {res['avg_gain']:+5.2f}% | 收益: {res['total_compound']:+6.1f}% | 回撤: {res['max_dd']:4.1f}%")
