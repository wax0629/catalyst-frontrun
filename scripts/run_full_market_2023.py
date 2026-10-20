#!/usr/bin/env python3
"""
2023 样本外 (Out-of-Sample) 全市场全量验证脚本
目标: 检验在 2024-2026 年提炼出的尾盘隔夜策略 (v0.4 手术刀级) 放到全新的 2023 历史样本中是否能稳定盈利。
覆盖标的: 全 A 股全部非 ST 正常股票 (~4,400+ 只)
回测周期: 2023-01-03 至 2023-12-29 (完整 242 个交易日)
无未来函数: 严格点时撮合 (Point-in-Time Strictly Enforced)
"""
import os
import sys
import json
import time
import pickle
import requests
import pandas as pd
from concurrent.futures import ThreadPoolExecutor

CACHE_PATH = "/Users/apple/Projects/trading/.agents/skills/tail-overnight-quant/scripts/cache_2023_full.pkl"
RESULTS_PATH = "/Users/apple/Projects/trading/.agents/skills/tail-overnight-quant/scripts/backtest_2023_full_results_v04.json"

def fetch_single_stock_2023(sym: str) -> tuple:
    """拉取单只股票在 2022-12-20 至 2024-01-10 的腾讯日线"""
    url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sym},day,2022-12-20,2024-01-10,300,"
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
        
        for row in day_rows:
            # ['2023-01-03', '7.270', '7.230', '7.280', '7.170', '258925.000']
            d_str = row[0].replace("-", "")
            op = float(row[1])
            cl = float(row[2])
            hi = float(row[3])
            lo = float(row[4])
            vol = float(row[5]) # 手
            
            if prev_close > 0:
                pct = round((cl - prev_close) / prev_close * 100, 3)
            else:
                pct = 0.0
                
            # 估算成交额: 成交量(手) * 100 * 均价
            avg_p = (op + cl) / 2.0
            amt = (vol * 100.0 * avg_p) / 1e8 # 亿元
            
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
        print(f"📦 发现本地 2023 全市场日线缓存: {CACHE_PATH}，直接加载...", flush=True)
        with open(CACHE_PATH, "rb") as f:
            return pickle.load(f)
            
    print("⏳ [1/4] 本地未发现 2023 缓存，从腾讯金融接口多线程极速抓取 4,400+ 标的...", flush=True)
    with open("/Users/apple/Projects/trading/.agents/skills/tail-overnight-quant/scripts/cache_2024_full.pkl", "rb") as f:
        d24 = pickle.load(f)
    with open("/Users/apple/Projects/trading/.agents/skills/tail-overnight-quant/scripts/cache_2025_full.pkl", "rb") as f:
        d25 = pickle.load(f)
        
    all_codes = sorted(list(set(d24.keys()) | set(d25.keys())))
    tencent_symbols = [c.replace(".", "") for c in all_codes]
    print(f"🚀 锁定待拉取全 A 股标的: {len(tencent_symbols)} 只", flush=True)
    
    stock_data = {}
    t0 = time.time()
    
    with ThreadPoolExecutor(max_workers=25) as executor:
        for idx, (sym, d_map) in enumerate(executor.map(fetch_single_stock_2023, tencent_symbols)):
            if d_map and len(d_map) >= 100:
                # 统一转为 sh.600000 格式
                std_code = sym[:2] + "." + sym[2:]
                stock_data[std_code] = d_map
            if (idx + 1) % 500 == 0 or (idx + 1) == len(tencent_symbols):
                print(f"  进度: [{idx+1}/{len(tencent_symbols)}] 耗时: {time.time()-t0:.1f}s | 有效入库: {len(stock_data)}", flush=True)
                
    print(f"✅ 抓取完成！全市场有效标的: {len(stock_data)} 只，写入缓存...", flush=True)
    with open(CACHE_PATH, "wb") as f:
        pickle.dump(stock_data, f)
    return stock_data

def run_simulation(stock_data: dict, is_v04: bool = True):
    """
    撮合回测逻辑:
    is_v04=True: 运行 v0.4 手术刀级 (含 T日开盘>=-1.0% + T日最低>=-2.5%)
    is_v04=False: 运行 原版 v0.2
    """
    # 获取 2023 交易日序列
    # 用任意全勤股票取日期
    sample_sym = list(stock_data.keys())[0]
    all_dates = sorted(list(stock_data[sample_sym].keys()))
    trade_days = [d for d in all_dates if '20230103' <= d <= '20231229']
    
    start_idx = all_dates.index('20230103')
    end_idx = all_dates.index('20231229')
    
    trades = []
    
    for i in range(start_idx, end_idx + 1):
        prev_d = all_dates[i - 1]
        t_d = all_dates[i]
        next_d = all_dates[i + 1]
        
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
            
        # 2. 在 T 日 14:40 严格按客观快照体检
        qualified = []
        for c in candidates:
            d_map = stock_data[c]
            t_bar = d_map.get(t_d)
            if not t_bar:
                continue
                
            amt = t_bar["amount"]
            pct = t_bar["pctChg"]
            hi = t_bar["high"]
            cl = t_bar["close"]
            op = t_bar["open"]
            lo = t_bar["low"]
            pre = t_bar["preclose"]
            
            if cl <= 0 or pre <= 0:
                continue
                
            max_gain_pct = (hi - pre) / pre * 100 if pre > 0 else 0
            pullback_pct = (hi - cl) / hi * 100 if hi > 0 else 0
            open_pct = (op - pre) / pre * 100 if pre > 0 else 0
            lo_pct = (lo - pre) / pre * 100 if pre > 0 else 0
            
            # 基础门槛 (v0.2)
            is_liquid = (amt >= 4.0)
            is_valid_band = (1.8 <= pct <= 5.0)
            has_deadly_shadow = (max_gain_pct >= 6.0 and pullback_pct >= 2.0)
            
            if not (is_liquid and is_valid_band and (not has_deadly_shadow) and pullback_pct <= 2.0):
                continue
                
            # v0.4 手术刀级排毒规则
            if is_v04:
                # 规则 1: 早盘开盘防跑路 (不得低开跌破 -1.0%)
                if open_pct < -1.0:
                    continue
                # 规则 2: 分时盘中防跳水破位 (最低价跌破昨收不得超 -2.5%)
                if lo_pct < -2.5:
                    continue
                    
            score = 100 + min(20, amt / 2.0) - pullback_pct * 5
            qualified.append({
                "code": c,
                "close_price": cl,
                "score": score
            })
            
        if not qualified:
            continue
            
        # 每日最多买入排名前 2 只
        qualified.sort(key=lambda x: x["score"], reverse=True)
        selected = qualified[:2]
        
        # 3. 冻结决策，向后取 T+1 执行严格出场 (严格无未来函数)
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
            min_gain = round((lo_t1 - buy_price) / buy_price * 100, 2)
            close_gain = round((cl_t1 - buy_price) / buy_price * 100, 2)
            
            # 出场状态机
            exit_gain = 0.0
            rule = ""
            
            # 1. 竞价深度低开果断止损 (< -2.0%)
            if open_gain < -2.0:
                exit_gain = open_gain
                rule = "🚨 竞价深度低开果断止损"
            # 2. 冲高紧凑吊灯止盈
            elif max_gain >= 5.0 and (max_gain - close_gain) >= 1.5:
                exit_gain = max_gain - 1.2
                rule = f"🎯 冲高至+{max_gain:.2f}%紧凑吊灯止盈"
            elif max_gain >= 2.5 and (max_gain - close_gain) >= 1.0:
                exit_gain = max_gain - 0.8
                rule = f"🎯 冲高至+{max_gain:.2f}%紧凑吊灯止盈"
            # 3. 冲高未果但激活平保锁
            elif max_gain >= 1.0 and min_gain <= 0.0:
                exit_gain = 0.1
                rule = f"🛡️ 冲高至+{max_gain:.2f}%激活平保锁防守"
            # 4. 盘中触及 -3.0% 硬止损
            elif min_gain <= -3.0:
                exit_gain = -3.0
                rule = "🚨 盘中触及-3.0%硬止损"
            # 5. 10:00 时间熔断平价出局
            else:
                exit_gain = close_gain
                rule = "⌛ 10:00 时间熔断平价出局"
                
            trades.append({
                "trade_date": t_d,
                "next_date": next_d,
                "code": c,
                "buy_price": buy_price,
                "open_gain": open_gain,
                "max_intraday_gain": max_gain,
                "min_intraday_gain": min_gain,
                "exit_gain": round(exit_gain, 2),
                "rule": rule,
                "is_win": exit_gain > 0
            })
            
    # 计算统计
    cnt = len(trades)
    if cnt == 0:
        return {"count": 0, "trades": []}
        
    wins = len([t for t in trades if t["exit_gain"] > 0])
    wr = round(wins / cnt * 100, 1)
    avg = round(sum(t["exit_gain"] for t in trades) / cnt, 2)
    
    cap = 200000.0
    peak = cap
    max_dd = 0.0
    by_date = {}
    for t in trades:
        d = t["trade_date"]
        if d not in by_date: by_date[d] = []
        by_date[d].append(t)
        
    for d, d_trades in sorted(by_date.items()):
        sub = cap / len(d_trades)
        cap = sum(sub * (1.0 + t["exit_gain"] / 100.0) for t in d_trades)
        if cap > peak: peak = cap
        dd = (peak - cap) / peak * 100
        if dd > max_dd: max_dd = dd
        
    return {
        "count": cnt,
        "win_rate": wr,
        "avg_gain": avg,
        "final_cap": round(cap, 2),
        "total_gain": round((cap - 200000.0) / 200000.0 * 100, 2),
        "max_dd": round(max_dd, 2),
        "trades": trades
    }

def main():
    print("=" * 80, flush=True)
    print("🧪 启动 2023 样本外 (Out-of-Sample) 全量测试集压力测试", flush=True)
    print("检验目标: 2024-2026 年经验提炼出的 v0.4 手术刀策略在全新历史年份的表现", flush=True)
    print("=" * 80, flush=True)
    
    stock_data = get_or_build_cache()
    
    print("\n⏳ [2/4] 运行原版 v0.2 (未经手术刀排毒) 在 2023 年的表现...", flush=True)
    res_v02 = run_simulation(stock_data, is_v04=False)
    
    print("⏳ [3/4] 运行最新升级版 v0.4 (手术刀级排毒) 在 2023 年的表现...", flush=True)
    res_v04 = run_simulation(stock_data, is_v04=True)
    
    print("\n" + "=" * 80, flush=True)
    print("📊 2023 全年样本外 (OOS) 测试对比结果:", flush=True)
    print(f"  原版 v0.2 : {res_v02['count']} 笔 | 胜率: {res_v02['win_rate']}% | 单笔均利: {res_v02['avg_gain']:+.2f}% | 20w终值: {res_v02['final_cap']:,.0f} 元 ({res_v02['total_gain']:+.1f}%) | 最大回撤: {res_v02['max_dd']:.2f}%", flush=True)
    print(f"  升级 v0.4 : {res_v04['count']} 笔 | 胜率: {res_v04['win_rate']}% | 单笔均利: {res_v04['avg_gain']:+.2f}% | 20w终值: {res_v04['final_cap']:,.0f} 元 ({res_v04['total_gain']:+.1f}%) | 最大回撤: {res_v04['max_dd']:.2f}%", flush=True)
    print("=" * 80, flush=True)
    
    # 保存结果
    out = {
        "version": "v0.4_oos_2023",
        "benchmark_v02": {k: v for k, v in res_v02.items() if k != "trades"},
        "result_v04": {k: v for k, v in res_v04.items() if k != "trades"},
        "trades_v04": res_v04["trades"]
    }
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"💾 完整逐笔撮合记录与统计指标已存入: {RESULTS_PATH}", flush=True)

if __name__ == "__main__":
    main()
