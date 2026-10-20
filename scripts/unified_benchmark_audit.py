import pickle
import json
import pandas as pd
import numpy as np

# 1. 统一加载沪深300
df_csi = pd.read_csv('/Users/apple/Projects/trading/.agents/skills/tail-overnight-quant/scripts/csi300_daily.csv')
csi_map = {}
for _, row in df_csi.iterrows():
    csi_map[str(int(row['date']))] = {
        'close': float(row['close']),
        'ma5': float(row['ma5']),
        'above_ma5': float(row['close']) >= float(row['ma5'])
    }

# 2. 统一加载 2023, 2024, 2025 股票全量日K缓存
print("正在载入全市场历史日K缓存...")
with open('/Users/apple/Projects/trading/.agents/skills/tail-overnight-quant/scripts/cache_2023_full.pkl', 'rb') as f:
    s23 = pickle.load(f)
with open('/Users/apple/Projects/trading/.agents/skills/tail-overnight-quant/scripts/cache_2024_full.pkl', 'rb') as f:
    s24 = pickle.load(f)
with open('/Users/apple/Projects/trading/.agents/skills/tail-overnight-quant/scripts/cache_2025_full.pkl', 'rb') as f:
    s25 = pickle.load(f)

# 2026 加载 enriched 完整交易
with open('/Users/apple/Projects/trading/.agents/skills/tail-overnight-quant/scripts/trades_2026_enriched.json') as f:
    t26_raw = json.load(f)

# 统一回测引擎 (严格点时无未来函数，20万本金，每笔最多50%仓位)
def run_audit(stock_data, start_date, end_date, v_type):
    sample_sym = list(stock_data.keys())[0]
    all_dates = sorted(list(stock_data[sample_sym].keys()))
    start_idx = all_dates.index(start_date)
    end_idx = all_dates.index(end_date)
    
    trades = []
    
    for i in range(start_idx, end_idx + 1):
        prev_d = all_dates[i - 1]
        t_d = all_dates[i]
        next_d = all_dates[i + 1]
        
        is_above_ma5 = csi_map.get(t_d, {'above_ma5': True})['above_ma5']
        
        # 版本规则分支:
        # V2: 宏观硬闸门
        if v_type == 'v03_ma5' and not is_above_ma5:
            continue
            
        # V4: 动态仓位权重
        if v_type == 'v05_volume':
            pos_weight = 1.0 if is_above_ma5 else 0.5
        else:
            pos_weight = 1.0
            
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
            
            # --- 基础过滤 (v0.2 Baseline) ---
            if amt < 4.0:
                continue
            if not (1.8 <= pct <= 5.0):
                continue
            if max_gain_pct >= 6.0 and pullback_pct >= 2.0:
                continue
            if pullback_pct > 2.0:
                continue
                
            # --- v0.4 & v0.5 手术刀去杂毛规则 ---
            if v_type in ['v04_surgical', 'v05_volume']:
                if open_pct < -1.0: # 剔除竞价低开抢跑
                    continue
                if lo_pct < -2.5:   # 剔除分时跳水破位
                    continue
                    
            # --- v0.5 独有成交量与流动性约束 ---
            if v_type == 'v05_volume':
                if amt > 14.0:      # 剔除熊市推不动的大象
                    continue
                if vr > 1.25:       # 剔除放量滞涨出货票
                    continue
                    
            # 打分机制
            score = 100 + min(20, amt / 2.0) - pullback_pct * 5
            qualified.append({"code": c, "close_price": cl, "score": score})
            
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
            cl_t1 = next_bar["close"]
            
            open_gain = round((op_t1 - buy_price) / buy_price * 100, 2)
            max_gain = round((hi_t1 - buy_price) / buy_price * 100, 2)
            close_gain = round((cl_t1 - buy_price) / buy_price * 100, 2)
            
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
                'trade_date': t_d,
                'code': c,
                'exit_gain': exit_gain,
                'pos_weight': pos_weight,
                'is_win': exit_gain > 0
            })
            
    return evaluate_trades(trades)

# 统一回测评估函数
def evaluate_trades(trades):
    if not trades:
        return {'count': 0, 'win_rate': 0.0, 'sum_gain': 0.0, 'final_cap': 200000.0, 'compound_ret': 0.0, 'max_dd': 0.0}
    
    cap = 200000.0
    cap_curve = [cap]
    
    for t in trades:
        # 单只股票最多分配账户 50% 资金，乘以动态仓位权重 pos_weight
        pos_cap = (cap * 0.5) * t.get('pos_weight', 1.0)
        pnl = pos_cap * (t['exit_gain'] / 100.0)
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
            
    wins = sum(1 for t in trades if t['is_win'])
    win_rate = round(wins / len(trades) * 100.0, 1)
    sum_gain = round(sum(t['exit_gain'] for t in trades), 2)
    compound_ret = round((cap - 200000.0) / 200000.0 * 100.0, 2)
    
    return {
        'count': len(trades),
        'win_rate': win_rate,
        'sum_gain': sum_gain,
        'final_cap': round(cap, 2),
        'compound_ret': compound_ret,
        'max_dd': round(max_dd, 1)
    }

# 2026 年评估逻辑 (从 trades_2026_enriched 中筛选)
def run_audit_2026(v_type):
    trades = []
    for t in t26_raw:
        t_d = t['trade_date']
        is_above_ma5 = csi_map.get(t_d, {'above_ma5': True})['above_ma5']
        
        if v_type == 'v03_ma5' and not is_above_ma5:
            continue
            
        pos_weight = 1.0
        if v_type == 'v05_volume':
            pos_weight = 1.0 if is_above_ma5 else 0.5
            
        open_pct = t.get('op_pct', 0.0)
        lo_pct = t.get('lo_pct', 0.0)
        
        if v_type in ['v04_surgical', 'v05_volume']:
            if open_pct < -1.0:
                continue
            if lo_pct < -2.5:
                continue
                
        trades.append({
            'trade_date': t_d,
            'code': t['code'],
            'exit_gain': t['exit_gain'],
            'pos_weight': pos_weight,
            'is_win': t['exit_gain'] > 0
        })
    return evaluate_trades(trades)

# 运行审计矩阵
matrix = {}
v_types = [
    ('v02_baseline', '1. 原版基准 (v0.2 Baseline: 无开盘过滤, 无MA5)'),
    ('v03_ma5',      '2. 宏观硬保护闸 (v0.3 MA5: 跌破5日线一律空仓)'),
    ('v04_surgical', '3. 手术刀微观排毒 (v0.4 Surgical: 剔除低开<-1%与跳水<-2.5%, 无MA5)'),
    ('v05_volume',   '4. 柔性量价与动态仓位 (v0.5 Volume: 剔除放量出货+弱势半仓防守)')
]

periods = [
    ('2023', s23, '20230103', '20231229'),
    ('2024', s24, '20240102', '20241231'),
    ('2025', s25, '20250102', '20251231'),
    ('2026', None, '', '')
]

results = {}
for code, name in v_types:
    results[code] = {'name': name, 'years': {}}
    for yr, data, s_d, e_d in periods:
        if yr == '2026':
            res = run_audit_2026(code)
        else:
            res = run_audit(data, s_d, e_d, code)
        results[code]['years'][yr] = res

# 打印严格对齐的审计报表
print("\n" + "="*85)
print("             【尾盘隔夜策略 4 年统一标准历史收益审计总账】")
print("  统一初始本金: 200,000元 | 单股仓位: 50%上限 | 严格逐日点时撮合无未来函数")
print("="*85)

for code, v_info in results.items():
    print(f"\n【{v_info['name']}】")
    print(f"{'年份':8s} | {'交易笔数':8s} | {'胜率':7s} | {'单利累加':10s} | {'20万终值':12s} | {'复利收益率':10s} | {'最大回撤':8s}")
    print("-" * 80)
    for yr in ['2023', '2024', '2025', '2026']:
        y_res = v_info['years'][yr]
        print(f"{yr:8s} | {y_res['count']:6d}笔 | {y_res['win_rate']:6.1f}% | {y_res['sum_gain']:+8.2f}% | {y_res['final_cap']:10,.0f}元 | {y_res['compound_ret']:+8.2f}% | {y_res['max_dd']:6.1f}%")

with open('/Users/apple/Projects/trading/.agents/skills/tail-overnight-quant/scripts/unified_audit_report.json', 'w') as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print("\n审计结果已存入 unified_audit_report.json")
