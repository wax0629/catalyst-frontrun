import pickle
import json
import pandas as pd
import numpy as np

# Load datasets
with open('/Users/apple/Projects/trading/.agents/skills/tail-overnight-quant/scripts/cache_2024_full.pkl', 'rb') as f:
    s24 = pickle.load(f)
with open('/Users/apple/Projects/trading/.agents/skills/tail-overnight-quant/scripts/cache_2025_full.pkl', 'rb') as f:
    s25 = pickle.load(f)
with open('/Users/apple/Projects/trading/.agents/skills/tail-overnight-quant/scripts/trades_2026_enriched.json') as f:
    d26 = json.load(f)
with open('/Users/apple/Projects/trading/.agents/skills/tail-overnight-quant/scripts/backtest_2024_full_market_v02.json') as f:
    d24 = json.load(f)
with open('/Users/apple/Projects/trading/.agents/skills/tail-overnight-quant/scripts/backtest_2025_full_market_v02.json') as f:
    d25 = json.load(f)

# Surgical filtered trades
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

print("基础手术刀样本数: 2024=%d笔, 2025=%d笔, 2026=%d笔" % (len(f24_surgical), len(f25_surgical), len(f26_surgical)))

# Analyze T+1 limit-up runners and what happens on T+2
def analyze_limit_up_extension(trades, stock_cache):
    sample_sym = list(stock_cache.keys())[0]
    all_dates = sorted(list(stock_cache[sample_sym].keys()))
    
    extended_trades = []
    limit_up_count = 0
    extra_profit = 0.0
    
    for t in trades:
        c = t['code']
        next_d = t['next_date']
        d_map = stock_cache.get(c, {})
        t1_bar = d_map.get(next_d)
        
        # Check if T+1 closed near limit up (pct >= 9.5% or close == high >= 9.0%)
        is_t1_limit_up = False
        if t1_bar:
            t1_cl = t1_bar['close']
            t1_hi = t1_bar['high']
            t1_pct = t1_bar['pctChg']
            is_gem = c.startswith('sz.30') or c.startswith('sh.68')
            lu_thresh = 19.0 if is_gem else 9.5
            if t1_pct >= lu_thresh or (t1_cl == t1_hi and t1_pct >= lu_thresh - 0.5):
                is_t1_limit_up = True
                
        if is_t1_limit_up and next_d in all_dates:
            t1_idx = all_dates.index(next_d)
            if t1_idx + 1 < len(all_dates):
                t2_d = all_dates[t1_idx + 1]
                t2_bar = d_map.get(t2_d)
                if t2_bar:
                    limit_up_count += 1
                    buy_p = t['buy_price']
                    t2_op = t2_bar['open']
                    t2_hi = t2_bar['high']
                    t2_open_gain = (t2_op - buy_p) / buy_p * 100.0
                    t2_max_gain = (t2_hi - buy_p) / buy_p * 100.0
                    # T+2 exit rule: if open gaps up high, take profit at open or trailing stop
                    new_exit = max(t['exit_gain'], t2_open_gain)
                    diff = new_exit - t['exit_gain']
                    extra_profit += diff
                    t_new = dict(t)
                    t_new['exit_gain'] = round(new_exit, 2)
                    t_new['rule'] = f"🚀 T+1封死涨停，持仓至T+2冲高止盈 (+{new_exit:.2f}%)"
                    extended_trades.append(t_new)
                    continue
        extended_trades.append(t)
        
    return extended_trades, limit_up_count, extra_profit

# Test extension on 2024 and 2025
e24, lu24, diff24 = analyze_limit_up_extension(f24_surgical, s24)
e25, lu25, diff25 = analyze_limit_up_extension(f25_surgical, s25)

print("\n【压榨空间 1：T+1 封涨停不卖，持股至 T+2 溢价出场】")
print(f"2024 年: 出现 {lu24} 笔 T+1 封死涨停，若持股至 T+2 卖出，累计多赚: +{diff24:.2f}% 收益！")
print(f"2025 年: 出现 {lu25} 笔 T+1 封死涨停，若持股至 T+2 卖出，累计多赚: +{diff25:.2f}% 收益！")

def run_portfolio_perf(trades, name):
    cap = 200000.0
    cap_curve = [cap]
    peak = cap
    max_dd = 0.0
    by_date = {}
    for t in trades:
        d = t['trade_date']
        if d not in by_date: by_date[d] = []
        by_date[d].append(t)
    for d, d_trades in sorted(by_date.items()):
        sub = cap / len(d_trades)
        cap = sum(sub * (1.0 + t['exit_gain'] / 100.0) for t in d_trades)
        if cap > peak: peak = cap
        dd = (peak - cap) / peak * 100
        if dd > max_dd: max_dd = dd
    ret = (cap - 200000.0) / 200000.0 * 100.0
    print(f"{name:30s} | 20万终值: {cap:10,.0f} 元 | 复利收益: {ret:+8.1f}% | 回撤: {max_dd:5.2f}%")
    return cap, ret

print("\n【收益对比：原版紧凑出场 vs 涨停连板持股溢价版】")
run_portfolio_perf(f24_surgical, "2024 原版出场")
cap24_ext, ret24_ext = run_portfolio_perf(e24, "2024 涨停连板溢价版")

run_portfolio_perf(f25_surgical, "2025 原版出场")
cap25_ext, ret25_ext = run_portfolio_perf(e25, "2025 涨停连板溢价版")
