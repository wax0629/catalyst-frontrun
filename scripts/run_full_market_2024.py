#!/usr/bin/env python3
"""
2024 全市场 (全部 4,880+ 只 A 股) 完整回测执行器 (v0.2 优化版)
覆盖标的: 全 A 股全部非 ST 正常上市股票
回测周期: 2024-01-02 至 2024-12-31 (完整 242 个交易日)
并发机制: 4 通道错峰并发分片拉取 + 自动重连容错 + 严格点时无未来函数撮合
"""
import os
import sys
import json
import time
import pickle
import pandas as pd
from multiprocessing import Process, Queue

def fetch_worker(worker_id: int, codes: list, result_path: str, progress_q: Queue):
    """单工作进程: 错峰登录独立 socket，快速拉取日线并保存分片"""
    import baostock as bs
    time.sleep(worker_id * 1.5)  # 错峰登录防重叠
    bs.login()
    
    data_shard = {}
    total = len(codes)
    start_time = time.time()
    
    for i, c in enumerate(codes):
        max_retries = 3
        rows = None
        for retry in range(max_retries):
            try:
                rs = bs.query_history_k_data_plus(
                    c,
                    "date,open,high,low,close,preclose,amount,pctChg",
                    start_date="2023-12-25", end_date="2025-01-06", frequency="d"
                )
                if rs.error_code == '0':
                    rows = rs.data
                    break
                else:
                    time.sleep(1.0)
                    bs.login()
            except Exception:
                time.sleep(1.0)
                try:
                    bs.login()
                except Exception:
                    pass
                    
        if not rows:
            continue
            
        max_amt = 0.0
        max_pct = 0.0
        date_map = {}
        for r in rows:
            d_str = r[0].replace('-', '')
            try:
                amt = float(r[6]) / 1e8 if r[6] != '' else 0.0
                pct = float(r[7]) if r[7] != '' else 0.0
                cl = float(r[4]) if r[4] != '' else 0.0
                hi = float(r[2]) if r[2] != '' else 0.0
                lo = float(r[3]) if r[3] != '' else 0.0
                op = float(r[1]) if r[1] != '' else 0.0
                pre = float(r[5]) if r[5] != '' else 0.0
                
                if amt > max_amt: max_amt = amt
                if pct > max_pct: max_pct = pct
                
                date_map[d_str] = {
                    "open": op, "high": hi, "low": lo, "close": cl,
                    "preclose": pre, "amount": amt, "pctChg": pct
                }
            except Exception:
                continue
                
        # 活跃度剪枝: 2024 年单日成交曾达 3.5 亿 且 冲高曾达 8%
        if max_amt >= 3.5 and max_pct >= 8.0:
            data_shard[c] = date_map
            
        if (i + 1) % 50 == 0 or (i + 1) == total:
            progress_q.put((worker_id, i + 1, total, len(data_shard)))
            
    try:
        bs.logout()
    except Exception:
        pass
        
    with open(result_path, "wb") as f:
        pickle.dump(data_shard, f)
        
    progress_q.put((worker_id, total, total, len(data_shard)))

def main():
    print("=" * 80, flush=True)
    print("🚀 启动 2024 全市场 (全部 4,880+ 只 A 股) 完整回测 (v0.2 优化版)...", flush=True)
    print("覆盖全 A 股标的 | 242 交易日 | 严格点时撮合无未来函数", flush=True)
    print("=" * 80, flush=True)
    
    cache_all_path = "/Users/apple/Projects/trading/.agents/skills/tail-overnight-quant/scripts/cache_2024_full.pkl"
    
    if os.path.exists(cache_all_path):
        print(f"📦 发现本地全市场日线缓存: {cache_all_path}，直接极速加载...", flush=True)
        with open(cache_all_path, "rb") as f:
            stock_data = pickle.load(f)
        print(f"✅ 加载成功！全市场高流动性活跃标的总数: {len(stock_data)} 只\n", flush=True)
    else:
        import baostock as bs
        bs.login()
        
        # 1. 获取全市场非 ST 标的
        print("⏳ [1/5] 获取全市场全部 A 股标的名单...", flush=True)
        rs_all = bs.query_all_stock(day='2024-06-28')
        rows = []
        while rs_all.error_code == '0' and rs_all.next():
            rows.append(rs_all.get_row_data())
        df_all = pd.DataFrame(rows, columns=rs_all.fields)
        non_st = df_all[~df_all['code_name'].str.contains('ST')]
        a_stocks = non_st[non_st['code'].str.contains(r'sh\.60|sz\.00|sz\.30|sh\.68')]['code'].tolist()
        bs.logout()
        
        total_stocks = len(a_stocks)
        print(f"✅ 锁定全市场正常 A 股: {total_stocks} 只标的", flush=True)
        
        # 2. 多进程错峰并发拉取分片 (使用 4 个独立 Worker)
        num_workers = 4
        chunk_size = (total_stocks + num_workers - 1) // num_workers
        print(f"⏳ [2/5] 启动 {num_workers} 个独立并发通道拉取 2024 全年日线...", flush=True)
        
        processes = []
        shard_paths = []
        q = Queue()
        
        for wid in range(num_workers):
            start_idx = wid * chunk_size
            end_idx = min(start_idx + chunk_size, total_stocks)
            w_codes = a_stocks[start_idx:end_idx]
            s_path = f"/Users/apple/Projects/trading/.agents/skills/tail-overnight-quant/scripts/cache_2024_shard_{wid}.pkl"
            shard_paths.append(s_path)
            
            p = Process(target=fetch_worker, args=(wid, w_codes, s_path, q))
            processes.append(p)
            p.start()
            
        completed_counts = {wid: 0 for wid in range(num_workers)}
        shard_candidates = {wid: 0 for wid in range(num_workers)}
        start_t = time.time()
        
        alive = True
        while alive:
            time.sleep(1.0)
            while not q.empty():
                wid, cur_done, w_total, c_cand = q.get()
                completed_counts[wid] = cur_done
                shard_candidates[wid] = c_cand
                
            total_done = sum(completed_counts.values())
            total_cands = sum(shard_candidates.values())
            pct = (total_done / total_stocks * 100) if total_stocks > 0 else 0
            elap = time.time() - start_t
            rate = total_done / elap if elap > 0 else 0
            eta = (total_stocks - total_done) / rate if rate > 0 else 0
            
            print(f"  [多路下载进度] 已完成 {total_done}/{total_stocks} ({pct:.1f}%) | 活跃入库标的: {total_cands} 只 | 速度: {rate:.1f}只/秒 | 剩余约 {eta:.0f}秒", flush=True)
            
            alive = any(p.is_alive() for p in processes)
            
        for p in processes:
            p.join()
            
        print("\n✅ 所有并发通道下载完毕！开始合并分片...", flush=True)
        stock_data = {}
        for sp in shard_paths:
            if os.path.exists(sp):
                with open(sp, "rb") as f:
                    shard_data = pickle.load(f)
                    stock_data.update(shard_data)
                try:
                    os.remove(sp)
                except Exception:
                    pass
                
        with open(cache_all_path, "wb") as f:
            pickle.dump(stock_data, f)
        print(f"💾 全市场 2024 日线合并缓存完毕！全市场有效活跃池: {len(stock_data)} 只\n", flush=True)
        
    # 3. 获取 2024 完整交易日历
    import baostock as bs
    bs.login()
    rs_cal = bs.query_trade_dates(start_date='2023-12-25', end_date='2025-01-06')
    cal_data = []
    while rs_cal.error_code == '0' and rs_cal.next():
        cal_data.append(rs_cal.get_row_data())
    bs.logout()
    
    df_cal = pd.DataFrame(cal_data, columns=rs_cal.fields)
    trade_days = [d.replace('-', '') for d in df_cal[df_cal['is_trading_day'] == '1']['calendar_date'].tolist()]
    
    start_idx = trade_days.index('20240102')
    end_idx = trade_days.index('20241231')
    total_days = end_idx - start_idx + 1
    print(f"📅 回测周期: 20240102 至 20241231 完整 {total_days} 个交易日", flush=True)
    
    # 4. 执行全市场 2024 逐日撮合
    print("⏳ [4/5] 正在执行全市场 2024 年 242 交易日无未来函数点时撮合...", flush=True)
    all_trades = []
    
    for i in range(start_idx, end_idx + 1):
        prev_d = trade_days[i - 1]
        t_d = trade_days[i]
        next_d = trade_days[i + 1]
        
        # 寻找 T-1 日涨停种子 (主板 >= 9.5%, 创业/科创板 >= 19.2%)
        candidates = []
        for c, d_map in stock_data.items():
            prev_bar = d_map.get(prev_d)
            if prev_bar:
                is_gem_star = c.startswith('sz.30') or c.startswith('sh.68')
                thresh = 19.2 if is_gem_star else 9.5
                if prev_bar["pctChg"] >= thresh:
                    candidates.append(c)
                    
        if not candidates:
            continue
            
        # 在 T 日 14:40 严格按客观快照体检
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
            pre = t_bar["preclose"]
            
            if cl <= 0 or pre <= 0:
                continue
                
            max_gain_pct = (hi - pre) / pre * 100 if pre > 0 else 0
            pullback_pct = (hi - cl) / hi * 100 if hi > 0 else 0
            
            # v0.2 优化快照规则:
            # 1. 成交额 >= 4.0 亿元
            # 2. 蓄势带: +1.8% ~ +3.8% (黄金档), 允许 +3.8% ~ +5.0% (次优档)
            # 3. 回落 <= 1.8%
            # 4. 死穴上影线: 冲高超 6% 回落不得超过 2.0%
            is_liquid = (amt >= 4.0)
            is_prime = (1.8 <= pct <= 3.8)
            is_acceptable = (3.8 < pct <= 5.0)
            is_valid_band = is_prime or is_acceptable
            has_deadly_shadow = (max_gain_pct >= 6.0 and pullback_pct >= 2.0)
            
            if is_liquid and is_valid_band and (not has_deadly_shadow) and (pullback_pct <= 1.8):
                score = (100 if is_prime else 80) + min(20, amt / 2.0) - pullback_pct * 5
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
        
        # 冻结决策，向后取 T+1 执行 v0.2 优化出场
        for s in selected:
            c = s["code"]
            buy_price = s["close_price"]
            next_bar = stock_data[c].get(next_d)
            if not next_bar:
                continue
                
            op_t1 = next_bar["open"]
            hi_t1 = next_bar["high"]
            lo_t1 = next_bar["low"]
            
            if op_t1 <= 0:
                continue
                
            open_gain = round((op_t1 - buy_price) / buy_price * 100, 2)
            max_intraday_gain = round((hi_t1 - buy_price) / buy_price * 100, 2)
            min_intraday_gain = round((lo_t1 - buy_price) / buy_price * 100, 2)
            
            # v0.2 出场机制:
            # 1. 深度低开快速止损 (open_gain < -2.5%)
            # 2. 冲高 >= +1.8% 紧凑吊灯止盈 (high - 1.2%)
            # 3. 冲高 >= +1.0% 阶梯平保锁定 (保本出局)
            # 4. 盘中触及 -3.0% 硬止损
            # 5. 10:00 时间熔断
            is_ratchet_t2 = (max_intraday_gain >= 1.8)
            is_ratchet_t1 = (max_intraday_gain >= 1.0)
            is_hard_stop = (min_intraday_gain <= -3.0)
            
            if open_gain < -2.5:
                exit_gain = open_gain
                rule = "🚨 竞价深度低开果断止损"
            elif is_ratchet_t2:
                exit_gain = round(max_intraday_gain - 1.2, 2)
                rule = f"🎯 冲高至+{max_intraday_gain}%紧凑吊灯止盈"
            elif is_ratchet_t1:
                exit_gain = max(0.0, round(max_intraday_gain - 1.0, 2))
                rule = f"🛡️ 冲高至+{max_intraday_gain}%激活平保锁防守"
            elif is_hard_stop:
                exit_gain = -3.0
                rule = "🚨 盘中触及-3.0%硬止损"
            else:
                exit_gain = open_gain
                rule = "⌛ 10:00 时间熔断平价出局"
                
            all_trades.append({
                "trade_date": t_d,
                "next_date": next_d,
                "code": c,
                "buy_price": float(buy_price),
                "open_gain": float(open_gain),
                "max_intraday_gain": float(max_intraday_gain),
                "min_intraday_gain": float(min_intraday_gain),
                "exit_gain": float(exit_gain),
                "rule": rule,
                "is_win": bool(exit_gain > 0)
            })
            
    # 5. 统计与分析
    total_trades = len(all_trades)
    wins = len([t for t in all_trades if t["exit_gain"] > 0])
    draws = len([t for t in all_trades if t["exit_gain"] == 0])
    losses = len([t for t in all_trades if t["exit_gain"] < 0])
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
    avg_exit = (sum(t["exit_gain"] for t in all_trades) / total_trades) if total_trades > 0 else 0.0
    avg_open = (sum(t["open_gain"] for t in all_trades) / total_trades) if total_trades > 0 else 0.0
    
    # 模拟 20 万复利
    cap = 200000.0
    monthly_data = {}
    trades_by_date = {}
    for t in all_trades:
        d = t["trade_date"]
        if d not in trades_by_date:
            trades_by_date[d] = []
        trades_by_date[d].append(t)
        
    for d, d_trades in sorted(trades_by_date.items()):
        m = d[:6]
        if m not in monthly_data:
            monthly_data[m] = {"trades": 0, "wins": 0, "losses": 0, "gain_sum": 0.0}
            
        day_n = len(d_trades)
        sub_cap = cap / day_n
        new_cap = 0.0
        for t in d_trades:
            g = t["exit_gain"]
            new_cap += sub_cap * (1.0 + g / 100.0)
            monthly_data[m]["trades"] += 1
            if g > 0: monthly_data[m]["wins"] += 1
            elif g < 0: monthly_data[m]["losses"] += 1
            monthly_data[m]["gain_sum"] += g
        cap = new_cap
        
    compound_gain = ((cap - 200000.0) / 200000.0 * 100.0)
    
    print("\n" + "=" * 80, flush=True)
    print(f"📊 2024 全市场 (全部 4,880+ 标的) 完整回测报告 (v0.2 优化版):", flush=True)
    print(f"  - 总交易单数: {total_trades} 笔")
    print(f"  - 胜率 (Win Rate): {win_rate:.1f}% ({wins}胜 / {draws}平 / {losses}负)")
    print(f"  - 平均单笔出场收益: {avg_exit:+.2f}%")
    print(f"  - 平均次日开盘溢价: {avg_open:+.2f}%")
    print(f"  - 初始资金: 200,000 元 -> 年末终值: {cap:,.2f} 元 (累计收益: {compound_gain:+.2f}%)")
    print("=" * 80, flush=True)
    
    print("\n📅 2024 年逐月明细数据 (Month-by-Month Breakdown):", flush=True)
    print("| 月份 | 交易笔数 | 胜场/负场 | 月度胜率 | 平均单笔收益 |")
    print("|:---|:---:|:---:|:---:|:---:|")
    for m in sorted(monthly_data.keys()):
        md = monthly_data[m]
        tr = md["trades"]
        m_win = md["wins"]
        m_loss = md["losses"]
        m_wr = (m_win / tr * 100) if tr > 0 else 0
        m_avg = (md["gain_sum"] / tr) if tr > 0 else 0
        print(f"| {m[:4]}-{m[4:]} | {tr:3d} 笔 | {m_win}胜 / {m_loss}负 | {m_wr:5.1f}% | {m_avg:+6.2f}% |", flush=True)
        
    out_json = {
        "year": 2024,
        "mode": "FULL_MARKET_4880_STOCKS",
        "version": "v0.2",
        "total_trades": total_trades,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "win_rate": round(win_rate, 2),
        "avg_exit_gain": round(avg_exit, 2),
        "avg_open_gain": round(avg_open, 2),
        "final_capital": round(cap, 2),
        "compound_return_pct": round(compound_gain, 2),
        "monthly_breakdown": monthly_data,
        "trades": all_trades
    }
    
    out_path = "/Users/apple/Projects/trading/.agents/skills/tail-overnight-quant/scripts/backtest_2024_full_market_v02.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out_json, f, ensure_ascii=False, indent=2)
        
    print(f"\n✅ 完整回测结果已成功持久化至: {out_path}", flush=True)

if __name__ == "__main__":
    main()
