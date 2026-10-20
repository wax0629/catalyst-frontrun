import pickle
import json
import pandas as pd
import numpy as np

# Load caches
with open('/Users/apple/Projects/trading/.agents/skills/tail-overnight-quant/scripts/cache_2023_full.pkl', 'rb') as f:
    s23 = pickle.load(f)
with open('/Users/apple/Projects/trading/.agents/skills/tail-overnight-quant/scripts/cache_2024_full.pkl', 'rb') as f:
    s24 = pickle.load(f)
with open('/Users/apple/Projects/trading/.agents/skills/tail-overnight-quant/scripts/cache_2025_full.pkl', 'rb') as f:
    s25 = pickle.load(f)

with open('/Users/apple/Projects/trading/.agents/skills/tail-overnight-quant/scripts/backtest_2024_full_market_v02.json') as f:
    d24 = json.load(f)
with open('/Users/apple/Projects/trading/.agents/skills/tail-overnight-quant/scripts/backtest_2025_full_market_v02.json') as f:
    d25 = json.load(f)
with open('/Users/apple/Projects/trading/.agents/skills/tail-overnight-quant/scripts/trades_2026_enriched.json') as f:
    d26 = json.load(f)
with open('/Users/apple/Projects/trading/.agents/skills/tail-overnight-quant/scripts/backtest_2023_full_results_v04.json') as f:
    d23 = json.load(f)

def calc_mainboard_daily_turnover(stock_cache):
    daily_amt = {}
    for c, d_map in stock_cache.items():
        if c.startswith('sh.60') or c.startswith('sz.00'):
            for d, bar in d_map.items():
                amt = bar.get('amount', 0.0)
                daily_amt[d] = daily_amt.get(d, 0.0) + amt
    return daily_amt

amt_map_23 = calc_mainboard_daily_turnover(s23)
amt_map_24 = calc_mainboard_daily_turnover(s24)
amt_map_25 = calc_mainboard_daily_turnover(s25)

# Surgical trade lists
f24_surgical = []
for t in d24['trades']:
    c = t['code']
    d = t['trade_date']
    bar = s24.get(c, {}).get(d)
    if not bar: continue
    pre = bar['preclose']
    op_pct = (bar['open'] - pre) / pre * 100 if pre > 0 else 0
    lo_pct = (bar['low'] - pre) / pre * 100 if pre > 0 else 0
    if op_pct >= -1.0 and lo_pct >= -2.5:
        f24_surgical.append(t)

f25_surgical = []
for t in d25['trades']:
    c = t['code']
    d = t['trade_date']
    bar = s25.get(c, {}).get(d)
    if not bar: continue
    pre = bar['preclose']
    op_pct = (bar['open'] - pre) / pre * 100 if pre > 0 else 0
    lo_pct = (bar['low'] - pre) / pre * 100 if pre > 0 else 0
    if op_pct >= -1.0 and lo_pct >= -2.5:
        f25_surgical.append(t)

f26_surgical = [t for t in d26 if t.get('op_pct', 0) >= -1.0 and t.get('lo_pct', 0) >= -2.5]
f23_surgical = d23['trades_v04']

def run_portfolio(trades, amt_map, shutdown_thresh=3800.0, mode='shutdown'):
    by_date = {}
    for t in trades:
        d = t['trade_date']
        if d not in by_date:
            by_date[d] = []
        by_date[d].append(t)
        
    cap = 200000.0
    cap_curve = [cap]
    peak = cap
    max_dd = 0.0
    total_trades_cnt = 0
    wins_cnt = 0
    
    for d, d_trades in sorted(by_date.items()):
        m_amt = amt_map.get(d, 5000.0)
        is_low_volume = (m_amt < shutdown_thresh)
        
        if is_low_volume:
            if mode == 'shutdown':
                continue # 完全空仓，一股不买！
            elif mode == 'half':
                daily_alloc = 0.5
            else:
                daily_alloc = 1.0
        else:
            daily_alloc = 1.0
            
        trade_cap = (cap * daily_alloc) / len(d_trades)
        day_pnl = 0.0
        for t in d_trades:
            gain = t['exit_gain']
            total_trades_cnt += 1
            if gain > 0:
                wins_cnt += 1
            day_pnl += trade_cap * (gain / 100.0)
            
        cap += day_pnl
        cap_curve.append(cap)
        if cap > peak: peak = cap
        dd = (peak - cap) / peak * 100.0
        if dd > max_dd: max_dd = dd
        
    wr = round(wins_cnt / total_trades_cnt * 100.0, 1) if total_trades_cnt > 0 else 0.0
    compound_ret = round((cap - 200000.0) / 200000.0 * 100.0, 1)
    return {
        'count': total_trades_cnt,
        'win_rate': wr,
        'final_cap': round(cap, 0),
        'compound_ret': compound_ret,
        'max_dd': round(max_dd, 2)
    }

all_datasets = [
    ('2023 (大熊市)', f23_surgical, amt_map_23),
    ('2024 (巨震反弹)', f24_surgical, amt_map_24),
    ('2025 (分化牛市)', f25_surgical, amt_map_25),
    ('2026 (当前行情)', f26_surgical, {})
]

print("\n" + "="*88)
print("  【策略终极大决战】v0.4 纯手术刀 VS v0.5 半仓防守 VS v0.6 地量完全空仓(一股不买)")
print("="*88)

for mode_name, m_key in [
    ('1. v0.4 纯手术刀原版 (无视成交量, 全天候满仓)', 'full'),
    ('2. v0.5 成交量变速箱 (地量时单笔半仓防守)', 'half'),
    ('3. v0.6 绝对地量清仓令 (地量时 100% 空仓, 一股不买)', 'shutdown')
]:
    print(f"\n【模式: {mode_name}】")
    print(f"{'年份':14s} | {'交易笔数':8s} | {'胜率':7s} | {'20万终值':14s} | {'复利收益率':10s} | {'最大回撤':8s}")
    print("-" * 75)
    caps = {}
    for y_name, t_list, a_map in all_datasets:
        r = run_portfolio(t_list, a_map, shutdown_thresh=3800.0, mode=m_key)
        caps[y_name] = r['compound_ret']
        print(f"{y_name:14s} | {r['count']:6d}笔 | {r['win_rate']:6.1f}% | {r['final_cap']:10,.0f} 元 | {r['compound_ret']:+8.1f}% | {r['max_dd']:6.2f}%")
        
    c_3yr = 200000.0 * (1 + caps['2024 (巨震反弹)']/100) * (1 + caps['2025 (分化牛市)']/100) * (1 + caps['2026 (当前行情)']/100)
    print(f"  >>> 2024~2026 三年利滚利终值: {c_3yr:,.0f} 元 (+{(c_3yr-200000)/200000*100:.1f}%)")
