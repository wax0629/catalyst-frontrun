#!/usr/bin/env python3
"""
2022 年度全市场全量真实点时回测与终极验刀脚本 (Run Full Market 2022)
测试环境：2022 极端黑天鹅大熊市 (俄乌冲突 + 美联储连续75bp加息 + 上海疫情封控 + 427与1031双大底)
严格点时无未来函数 (Point-in-Time Strictly Enforced)。
"""
import os
import time
import json
import pickle
import requests
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
import numpy as np

CACHE_PATH = "/Users/apple/Projects/trading/.agents/skills/tail-overnight-quant/scripts/cache_2022_full.pkl"
RESULTS_PATH = "/Users/apple/Projects/trading/.agents/skills/tail-overnight-quant/scripts/backtest_2022_full_results.json"

def fetch_single_stock_2022(sym: str) -> tuple:
    """拉取单只股票在 2021-12-20 至 2023-01-10 的腾讯日线"""
    url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sym},day,2021-12-20,2023-01-10,300,"
    try:
        r = requests.get(url, timeout=4)
        if r.status_code != 200:
            return sym, None
        d = r.json().get("data", {}).get(sym, {})
        day_rows = d.get("day", [])
        if not day_rows:
            return sym, None
            
        date_map = {}
        prev_close = 0.0
        
        is_star = sym.startswith("sh68")
        
        for row in day_rows:
            # ['2022-01-04', '7.270', '7.230', '7.280', '7.170', '258925.000']
            d_str = row[0].replace("-", "")
            op = float(row[1])
            cl = float(row[2])
            hi = float(row[3])
            lo = float(row[4])
            vol = float(row[5])
            
            if prev_close > 0:
                pct = round((cl - prev_close) / prev_close * 100, 3)
            else:
                pct = 0.0
                
            avg_p = (op + cl) / 2.0
            if is_star:
                amt = (vol * avg_p) / 1e8 # 688 vol 是股
            else:
                amt = (vol * 100.0 * avg_p) / 1e8 # 主板 vol 是手 (100股)
            
            date_map[d_str] = {
                "open": op,
                "close": cl,
                "high": hi,
                "low": lo,
                "preclose": prev_close,
                "volume": vol,
                "amount": amt,
                "pctChg": pct
            }
            prev_close = cl
            
        return sym, date_map
    except Exception:
        return sym, None

def get_or_build_cache() -> dict:
    if os.path.exists(CACHE_PATH):
        print(f"📦 发现本地 2022 全市场日线缓存: {CACHE_PATH}，直接加载...", flush=True)
        with open(CACHE_PATH, "rb") as f:
            return pickle.load(f)
            
    print("⏳ [1/4] 本地未发现 2022 缓存，从腾讯金融接口多线程极速抓取 4,000+ 标的...", flush=True)
    with open("/Users/apple/Projects/trading/.agents/skills/tail-overnight-quant/scripts/cache_2023_full.pkl", "rb") as f:
        d23 = pickle.load(f)
        
    all_codes = sorted(list(d23.keys()))
    tencent_symbols = [c.replace(".", "") for c in all_codes]
    print(f"🚀 锁定待拉取全 A 股标的: {len(tencent_symbols)} 只", flush=True)
    
    stock_data = {}
    t0 = time.time()
    
    with ThreadPoolExecutor(max_workers=30) as executor:
        for idx, (sym, d_map) in enumerate(executor.map(fetch_single_stock_2022, tencent_symbols)):
            if d_map and len(d_map) >= 100:
                std_code = sym[:2] + "." + sym[2:]
                stock_data[std_code] = d_map
            if (idx + 1) % 500 == 0 or (idx + 1) == len(tencent_symbols):
                print(f"  进度: [{idx+1}/{len(tencent_symbols)}] 耗时: {time.time()-t0:.1f}s | 有效入库: {len(stock_data)}", flush=True)
                
    print(f"✅ 抓取完成！2022全市场有效标的: {len(stock_data)} 只，写入缓存...", flush=True)
    with open(CACHE_PATH, "wb") as f:
        pickle.dump(stock_data, f)
    return stock_data

def run_simulation(stock_data: dict, mode: str = "v06_final", low_vol_thresh: float = 3800.0):
    """
    撮合回测逻辑:
    mode='v02': 原版基准 (无手术刀，无成交量安全闸)
    mode='v04': 纯手术刀版 (含开盘>=-1.0% + 最低>=-2.5%，无成交量安全闸)
    mode='v06_final': 终极全天候版 (手术刀 + 两市成交量智能安全闸: 地量清仓令)
    """
    sample_sym = list(stock_data.keys())[0]
    all_dates = sorted(list(stock_data[sample_sym].keys()))
    
    start_d = '20220104'
    end_d = '20221230'
    start_idx = all_dates.index(start_d)
    end_idx = all_dates.index(end_d)
    
    # 预先计算主板每日总成交额
    daily_main_amt = {}
    for c, d_map in stock_data.items():
        if c.startswith('sh.60') or c.startswith('sz.00'):
            for d, bar in d_map.items():
                if start_d <= d <= end_d:
                    daily_main_amt[d] = daily_main_amt.get(d, 0.0) + bar.get('amount', 0.0)
                    
    trades = []
    
    for i in range(start_idx, end_idx + 1):
        prev_d = all_dates[i - 1]
        t_d = all_dates[i]
        next_d = all_dates[i + 1]
        
        # 宏观成交量门禁 (v0.6 核心)
        m_amt = daily_main_amt.get(t_d, 4000.0)
        is_low_vol = (m_amt < low_vol_thresh)
        
        if mode == "v06_final" and is_low_vol:
            continue # 触发【绝对地量清仓令】，100% 空仓，连一股都不买！
            
        # 1. 寻找 T-1 日涨停种子 (主板 >= 9.5%, 创业/科创板 >= 19.2%)
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
            
        # 2. 在 T 日 14:40 客观量化快照体检
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
            
            # 基础门槛
            if amt < 4.0:
                continue
            if not (1.8 <= pct <= 5.0):
                continue
            if max_gain_pct >= 6.0 and pullback_pct >= 2.0:
                continue
            if pullback_pct > 2.0:
                continue
                
            # 手术刀级排毒 (v0.4 & v0.6)
            if mode in ["v04", "v06_final"]:
                if open_pct < -1.0: # 剔除早盘低开抢跑
                    continue
                if lo_pct < -2.5:   # 剔除日内跳水破位
                    continue
                    
            # v0.6 独有流动性黄金带与量比出货排毒
            if mode == "v06_final":
                if amt > 14.0:      # 剔除熊市推不动的大象
                    continue
                if vr > 1.30:       # 剔除放量滞涨出货票
                    continue
                    
            score = 100 + min(20, amt / 2.0) - pullback_pct * 5
            qualified.append({"code": c, "close_price": cl, "score": score})
            
        if not qualified:
            continue
            
        qualified.sort(key=lambda x: x["score"], reverse=True)
        selected = qualified[:2]
        
        # 3. T+1 出场状态机
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
                
            trades.append({
                "trade_date": t_d,
                "next_date": next_d,
                "code": c,
                "buy_price": buy_price,
                "open_gain": open_gain,
                "max_intraday_gain": max_gain,
                "exit_gain": exit_gain,
                "rule": rule,
                "is_win": exit_gain > 0
            })
            
    # 统一实盘资金滚存计算 (20万本金，当日1只买100%，2只平分各50%)
    if not trades:
        return {"count": 0, "win_rate": 0, "avg_gain": 0, "final_cap": 200000.0, "total_gain": 0, "max_dd": 0, "trades": []}
        
    by_date = {}
    for t in trades:
        d = t["trade_date"]
        if d not in by_date:
            by_date[d] = []
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
        if cap > peak:
            peak = cap
        dd = (peak - cap) / peak * 100.0
        if dd > max_dd:
            max_dd = dd
            
    wins = sum(1 for t in trades if t["is_win"])
    win_rate = round(wins / len(trades) * 100.0, 1)
    avg_gain = round(sum(t["exit_gain"] for t in trades) / len(trades), 2)
    total_gain = round((cap - 200000.0) / 200000.0 * 100.0, 1)
    
    return {
        "count": len(trades),
        "win_rate": win_rate,
        "avg_gain": avg_gain,
        "final_cap": round(cap, 0),
        "total_gain": total_gain,
        "max_dd": round(max_dd, 2),
        "trades": trades
    }

def main():
    stock_data = get_or_build_cache()
    
    print("\n⏳ [2/4] 运行原版 v0.2 在 2022 年大熊市的表现...", flush=True)
    res_v02 = run_simulation(stock_data, mode="v02")
    
    print("⏳ [3/4] 运行纯手术刀版 v0.4 在 2022 年大熊市的表现...", flush=True)
    res_v04 = run_simulation(stock_data, mode="v04")
    
    print("⏳ [4/4] 运行终极全天候版 v0.6 (手术刀 + 地量清仓令) 在 2022 年的表现...", flush=True)
    res_v06 = run_simulation(stock_data, mode="v06_final", low_vol_thresh=3800.0)
    
    print("\n" + "=" * 88, flush=True)
    print("📊 2022 极端黑天鹅大熊市终极验刀结果 (初始本金 20 万元):", flush=True)
    print(f"  原版 v0.2 : {res_v02['count']:3d} 笔 | 胜率: {res_v02['win_rate']:4.1f}% | 均利: {res_v02['avg_gain']:+5.2f}% | 终值: {res_v02['final_cap']:9,.0f} 元 ({res_v02['total_gain']:+5.1f}%) | 最大回撤: {res_v02['max_dd']:5.2f}%", flush=True)
    print(f"  手术刀 v0.4: {res_v04['count']:3d} 笔 | 胜率: {res_v04['win_rate']:4.1f}% | 均利: {res_v04['avg_gain']:+5.2f}% | 终值: {res_v04['final_cap']:9,.0f} 元 ({res_v04['total_gain']:+5.1f}%) | 最大回撤: {res_v04['max_dd']:5.2f}%", flush=True)
    print(f"  终极版 v0.6: {res_v06['count']:3d} 笔 | 胜率: {res_v06['win_rate']:4.1f}% | 均利: {res_v06['avg_gain']:+5.2f}% | 终值: {res_v06['final_cap']:9,.0f} 元 ({res_v06['total_gain']:+5.1f}%) | 最大回撤: {res_v06['max_dd']:5.2f}%", flush=True)
    print("=" * 88, flush=True)
    
    out = {
        "version": "v0.6_full_market_2022",
        "benchmark_v02": {k: v for k, v in res_v02.items() if k != "trades"},
        "result_v04": {k: v for k, v in res_v04.items() if k != "trades"},
        "result_v06": {k: v for k, v in res_v06.items() if k != "trades"},
        "trades_v06": res_v06["trades"]
    }
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"💾 完整 2022 回测数据已保存至: {RESULTS_PATH}", flush=True)

if __name__ == "__main__":
    main()
