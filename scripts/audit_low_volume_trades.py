import pickle
import json
import pandas as pd
import numpy as np

# Load datasets
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

# Mainboard daily turnover
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

# Associate each trade with market turnover
def tag_market_amt(trades, amt_map, default_amt=5000.0):
    for t in trades:
        t['m_amt'] = amt_map.get(t['trade_date'], default_amt)
    return trades

tag_market_amt(f23_surgical, amt_map_23)
tag_market_amt(f24_surgical, amt_map_24)
tag_market_amt(f25_surgical, amt_map_25)
tag_market_amt(f26_surgical, {}, default_amt=5500.0) # 2026 is high volume

all_trades_by_year = [
    ('2023', f23_surgical),
    ('2024', f24_surgical),
    ('2025', f25_surgical),
    ('2026', f26_surgical)
]

# Audit function for different thresholds
for thresh in [3500.0, 3800.0, 4000.0]:
    print("\n" + "="*85)
    print(f"【审计】当全市场主板成交额 < {thresh:.0f} 亿 (地量冰点期) 时的交易详细统计")
    print("="*85)
    
    total_low_trades = []
    
    for yr, tr_list in all_trades_by_year:
        low_t = [t for t in tr_list if t['m_amt'] < thresh]
        total_low_trades.extend(low_t)
        
        cnt = len(low_t)
        if cnt == 0:
            print(f"{yr} 年: 0 笔交易发生在成交额 < {thresh:.0f} 亿时 (全年在活跃区)")
            continue
            
        wins = [t['exit_gain'] for t in low_t if t['exit_gain'] > 0]
        losses = [t['exit_gain'] for t in low_t if t['exit_gain'] <= 0]
        
        wr = len(wins) / cnt * 100.0
        avg_win = np.mean(wins) if wins else 0.0
        avg_loss = np.mean(losses) if losses else 0.0 # negative
        sum_gain = sum(t['exit_gain'] for t in low_t)
        ev = (wr/100.0 * avg_win) + ((1.0 - wr/100.0) * avg_loss)
        plr = abs(avg_win / avg_loss) if avg_loss != 0 else 0.0
        
        print(f"{yr} 年地量期: {cnt:2d} 笔 | 胜率: {wr:4.1f}% | 均赚: +{avg_win:4.2f}% | 均亏: {avg_loss:4.2f}% | 盈亏比: {plr:4.2f} | 单笔期望EV: {ev:+5.2f}% | 累计盈亏: {sum_gain:+6.2f}%")
        
    print("-" * 85)
    all_cnt = len(total_low_trades)
    if all_cnt > 0:
        all_wins = [t['exit_gain'] for t in total_low_trades if t['exit_gain'] > 0]
        all_losses = [t['exit_gain'] for t in total_low_trades if t['exit_gain'] <= 0]
        tot_wr = len(all_wins) / all_cnt * 100.0
        tot_avg_win = np.mean(all_wins) if all_wins else 0.0
        tot_avg_loss = np.mean(all_losses) if all_losses else 0.0
        tot_sum = sum(t['exit_gain'] for t in total_low_trades)
        tot_ev = (tot_wr/100.0 * tot_avg_win) + ((1.0 - tot_wr/100.0) * tot_avg_loss)
        tot_plr = abs(tot_avg_win / tot_avg_loss) if tot_avg_loss != 0 else 0.0
        
        print(f"【4年全样本地量期汇总】:")
        print(f"  总交易笔数: {all_cnt} 笔")
        print(f"  总胜率:     {tot_wr:.1f}% ({len(all_wins)} 胜 / {len(all_losses)} 负)")
        print(f"  平均单笔盈利 (胜场): +{tot_avg_win:.2f}%")
        print(f"  平均单笔亏损 (负场): {tot_avg_loss:.2f}%")
        print(f"  盈亏比 (赔率):       {tot_plr:.2f}")
        print(f"  单笔数学期望 (EV):   {tot_ev:+.2f}%")
        print(f"  所有交易累计盈亏:    {tot_sum:+.2f}%")
        if tot_ev < 0:
            print(f"  >>> 结论: 数学期望为负 (EV < 0)！直接空仓完全不做的收益将净增 {abs(tot_sum):.2f}%！")
        else:
            print(f"  >>> 结论: 数学期望为正 (EV > 0)，妖股收益能覆盖亏损！")
