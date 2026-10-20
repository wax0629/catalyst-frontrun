import pickle
import json
import pandas as pd
import numpy as np

# 1. 载入缓存
print("载入 2023, 2024, 2025 日K缓存与 2026 交易...")
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

# 2. 计算各年份全市场主板日成交额 (亿元)
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

# 3. 提取 2024, 2025 手术刀基础交易
# 2024 手术刀 68 笔
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

# 2025 手术刀 107 笔
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

# 2026 手术刀 73 笔
f26_surgical = [t for t in d26 if t.get('op_pct', 0) >= -1.0 and t.get('lo_pct', 0) >= -2.5]

# 2023 手术刀 94 笔
f23_surgical = d23['trades_v04']

print(f"数据核验: 2023={len(f23_surgical)}笔, 2024={len(f24_surgical)}笔, 2025={len(f25_surgical)}笔, 2026={len(f26_surgical)}笔")

# 4. 回测回放引擎 (支持全仓模式与变速箱模式)
def simulate_portfolio(trades, amt_map, mode='surgical_v04', low_vol_thresh=3800.0):
    """
    mode='surgical_v04': 纯手术刀版 (基准)，有交易日100%全额平分
    mode='volume_gearbox': 市场成交量变速箱策略:
         - 若当天主板成交额 >= low_vol_thresh (常态/活跃区): 100% 满仓运作
         - 若当天主板成交额 < low_vol_thresh (地量冰点区): 50% 半仓防守运作
    """
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
    sum_gain = 0.0
    
    for d, d_trades in sorted(by_date.items()):
        # 获取当日成交量状态
        m_amt = amt_map.get(d, 5000.0) # 2026年两市成交均在万亿以上，主板>4000亿
        is_low_volume = (m_amt < low_vol_thresh)
        
        # 确定仓位利用率
        if mode == 'volume_gearbox' and is_low_volume:
            daily_allocation = 0.5 # 地量冰点区: 50% 半仓防守
        else:
            daily_allocation = 1.0 # 常态/充沛区: 100% 满仓出击
            
        trade_capital = (cap * daily_allocation) / len(d_trades)
        
        day_pnl = 0.0
        for t in d_trades:
            gain = t['exit_gain']
            total_trades_cnt += 1
            if gain > 0:
                wins_cnt += 1
            sum_gain += gain
            day_pnl += trade_capital * (gain / 100.0)
            
        cap += day_pnl
        cap_curve.append(cap)
        if cap > peak:
            peak = cap
        dd = (peak - cap) / peak * 100.0
        if dd > max_dd:
            max_dd = dd
            
    win_rate = round(wins_cnt / total_trades_cnt * 100.0, 1) if total_trades_cnt > 0 else 0.0
    compound_ret = round((cap - 200000.0) / 200000.0 * 100.0, 1)
    
    return {
        'count': total_trades_cnt,
        'win_rate': win_rate,
        'sum_gain': round(sum_gain, 1),
        'final_cap': round(cap, 0),
        'compound_ret': compound_ret,
        'max_dd': round(max_dd, 2)
    }

# 5. 执行对比测试
all_datasets = [
    ('2023 (大熊市)', f23_surgical, amt_map_23),
    ('2024 (巨震反弹)', f24_surgical, amt_map_24),
    ('2025 (分化牛市)', f25_surgical, amt_map_25),
    ('2026 (当前行情)', f26_surgical, {})
]

print("\n" + "="*88)
print("     【全量对比测试】v0.4 纯手术刀版 VS v0.5 市场成交量智能变速箱版")
print("  初始本金: 200,000 元 | 严格点时逐日真实撮合 | 2023~2026 全周期")
print("="*88)

print(f"\n【测试 1: v0.4 纯手术刀原版 (无成交量防守，全天候满仓)】")
print(f"{'年份':14s} | {'交易笔数':8s} | {'胜率':7s} | {'20万终值':14s} | {'复利收益率':10s} | {'最大回撤':8s}")
print("-" * 75)
res_v04 = {}
for y_name, t_list, a_map in all_datasets:
    r = simulate_portfolio(t_list, a_map, mode='surgical_v04')
    res_v04[y_name] = r
    print(f"{y_name:14s} | {r['count']:6d}笔 | {r['win_rate']:6.1f}% | {r['final_cap']:10,.0f} 元 | {r['compound_ret']:+8.1f}% | {r['max_dd']:6.2f}%")

print(f"\n【测试 2: v0.5 市场成交量智能变速箱 (充沛满仓 + 枯水地量半仓防守)】")
print(f"{'年份':14s} | {'交易笔数':8s} | {'胜率':7s} | {'20万终值':14s} | {'复利收益率':10s} | {'最大回撤':8s}")
print("-" * 75)
res_v05 = {}
for y_name, t_list, a_map in all_datasets:
    r = simulate_portfolio(t_list, a_map, mode='volume_gearbox', low_vol_thresh=3800.0)
    res_v05[y_name] = r
    print(f"{y_name:14s} | {r['count']:6d}笔 | {r['win_rate']:6.1f}% | {r['final_cap']:10,.0f} 元 | {r['compound_ret']:+8.1f}% | {r['max_dd']:6.2f}%")

# 6. 计算三年滚存 (2024 -> 2025 -> 2026)
c_v04 = 200000.0 * (1 + res_v04['2024 (巨震反弹)']['compound_ret']/100) * (1 + res_v04['2025 (分化牛市)']['compound_ret']/100) * (1 + res_v04['2026 (当前行情)']['compound_ret']/100)
c_v05 = 200000.0 * (1 + res_v05['2024 (巨震反弹)']['compound_ret']/100) * (1 + res_v05['2025 (分化牛市)']['compound_ret']/100) * (1 + res_v05['2026 (当前行情)']['compound_ret']/100)

print("\n" + "="*88)
print(f"三年复合滚存最终对比 (2024~2026 利滚利):")
print(f"  v0.4 纯手术刀原版: 200,000 元 -> {c_v04:,.0f} 元 (+{(c_v04-200000)/200000*100:.1f}%)")
print(f"  v0.5 成交量变速箱: 200,000 元 -> {c_v05:,.0f} 元 (+{(c_v05-200000)/200000*100:.1f}%)")
print("="*88)
