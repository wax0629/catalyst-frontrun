#!/usr/bin/env python3
"""
重大催化一手雷达与微观盘口探测器 (Catalyst Radar & Microstructure Inspector)

功能：
1. 实时抓取核心大盘指数（上证、深证、创业板、科创50）行情与流动性环境；
2. 实时监测催化跟踪池标的最新价格、涨跌幅、成交额与分时极值；
3. 判定当前标的所处的价格状态（萌芽静默期、主升脱离期、还是冲高阻力区）。
"""

import sys
import json
import urllib.request
import datetime

DEFAULT_TARGETS = [
    {"code": "sh600699", "name": "均胜电子", "thesis": "工信部L3级自动驾驶准入试点", "cost": 20.85, "support": 21.20, "target": 23.00},
    {"code": "sz002212", "name": "天融信", "thesis": "海外勒索病毒与四季度国企网安采购", "cost": 7.05, "support": 7.05, "target": 7.70},
]

MARKET_INDICES = [
    {"code": "sh000001", "name": "上证指数"},
    {"code": "sz399001", "name": "深证成指"},
    {"code": "sz399006", "name": "创业板指"},
    {"code": "sh000688", "name": "科创50"},
]

def fetch_quotes(code_list):
    url = "https://qt.gtimg.cn/q=" + ",".join(code_list)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            text = response.read().decode("gbk", errors="ignore")
            quotes = {}
            for line in text.strip().split(";"):
                if not line.strip():
                    continue
                parts = line.split("~")
                if len(parts) > 37:
                    q_code = parts[2]
                    quotes[q_code] = {
                        "name": parts[1],
                        "code": q_code,
                        "price": float(parts[3]) if parts[3] else 0.0,
                        "pre_close": float(parts[4]) if parts[4] else 0.0,
                        "open": float(parts[5]) if parts[5] else 0.0,
                        "change_pct": float(parts[32]) if parts[32] else 0.0,
                        "high": float(parts[33]) if parts[33] else 0.0,
                        "low": float(parts[34]) if parts[34] else 0.0,
                        "amount_yi": float(parts[37]) / 10000.0 if parts[37] else 0.0,
                        "time": parts[30],
                    }
            return quotes
    except Exception as e:
        print(f"[Error] 行情拉取失败: {e}", file=sys.stderr)
        return {}

def run_radar():
    print("=" * 70)
    print(" 📡 催化前瞻抢跑体系 · 实时大盘与持仓探测雷达")
    print(f" 运行时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # 1. 查询指数
    index_codes = [x["code"] for x in MARKET_INDICES]
    target_codes = [x["code"] for x in DEFAULT_TARGETS]
    all_codes = index_codes + target_codes

    quotes = fetch_quotes(all_codes)
    if not quotes:
        print("[Warn] 无法获取实时行情，请检查网络连接。")
        return

    print("\n【宏观与大盘流动性态势】:")
    total_market_turnover = 0.0
    for idx in MARKET_INDICES:
        raw_code = idx["code"][2:]
        q = quotes.get(raw_code)
        if q:
            total_market_turnover += q["amount_yi"]
            sign = "+" if q["change_pct"] > 0 else ""
            print(f"  • {q['name']:<6} ({q['code']}): {q['price']:>8.2f}  {sign}{q['change_pct']:>6.2f}%  成交: {q['amount_yi']:>7.2f} 亿 (高: {q['high']:.2f}, 低: {q['low']:.2f})")

    print(f"\n  >> 沪深主板合计成交额概算: ~{total_market_turnover:.2f} 亿元")
    if total_market_turnover >= 15000:
        print("  >> 流动性状态: 充沛放量环境（有利于题材发酵与多头主升）")
    elif total_market_turnover >= 10000:
        print("  >> 流动性状态: 正常均衡环境（结构性轮动与预期差博弈）")
    else:
        print("  >> 流动性状态: 存量萎缩弱势（严控开仓频率，防范补跌风险）")

    print("\n" + "-" * 70)
    print("【核心催化标的实时追踪与盈亏看板】:")
    for tgt in DEFAULT_TARGETS:
        raw_code = tgt["code"][2:]
        q = quotes.get(raw_code)
        if not q:
            continue

        cost = tgt["cost"]
        current_p = q["price"]
        pnl_pct = ((current_p - cost) / cost) * 100.0 if cost > 0 else 0.0
        pnl_sign = "+" if pnl_pct >= 0 else ""

        print(f"\n  🎯 [{tgt['name']}] ({q['code']}) — 催化逻辑: {tgt['thesis']}")
        print(f"     买入成本: {cost:.2f} 元 | 现价: {current_p:.2f} 元 ({pnl_sign}{pnl_pct:.2f}%) | 当日涨跌: {q['change_pct']:+.2f}%")
        print(f"     日内区间: [{q['low']:.2f} ~ {q['high']:.2f}] | 今日成交: {q['amount_yi']:.2f} 亿元")
        print(f"     防守支撑: {tgt['support']:.2f} 元 | 目标区间: {tgt['target']:.2f} 元")

        if current_p >= tgt["target"]:
            print("     💡 战术建议: 【触及目标阻力区】建议借市场情绪高潮分批减仓/全额止盈！")
        elif current_p < tgt["support"]:
            print("     ⚠️ 战术建议: 【跌破移动防守线】触及止损/保本平仓线，启动纪律出局！")
        elif pnl_pct >= 3.0:
            print("     🚀 战术建议: 【脱离成本区】浮盈充沛，持有底仓，上移止盈线，让利润奔跑！")
        else:
            print("     ⏳ 战术建议: 【成本震荡区】耐心等待催化发酵与分时确认。")

    print("\n" + "=" * 70)

if __name__ == "__main__":
    run_radar()
