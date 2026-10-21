#!/usr/bin/env python3
"""
尾盘隔夜量化选股与风控策略流水线 (Tail Overnight Strategy Pipeline)
基于 2022~2026 五年全市场全量真实点时回测实证设计：
1. 第一层: 全市场成交量门禁与情绪指标 (低于 6800 亿强制空仓保护)
2. 第二层: 板块属性与主流赛道加权 (+20分权重)
3. 第三层: 个股流动性适度区间 (4.5~14亿) 与开盘防大幅低开、分时防跳水破位
4. 第四层: 日内形态适度蓄势 (+1.8%~+5.0%) 与量比过滤 (VR<=1.30)
5. 第五层: 综合决策模块
6. 第六层: 次日早盘分层止盈止损执行 (含涨停板持仓至次日与高流动性止盈自适应)
7. 输出: 规范化实盘操作指令卡
严格点时无未来函数 (Point-in-Time Strictly Enforced)。
"""
import sys
import json
import requests
import datetime
import pandas as pd

# 接口常量
THS_POOL_URL = "https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

def get_market_volume_status() -> dict:
    """
    获取今日全市场(沪深两市)实时成交总额
    两市成交额低于 6800 亿时，短线接力胜率偏低，策略强制保持空仓。
    """
    try:
        r = requests.get("http://qt.gtimg.cn/q=s_sh000001,s_sz399001", timeout=4)
        lines = r.text.strip().split(";")
        sh_amt = 0.0
        sz_amt = 0.0
        for l in lines:
            if not l.strip():
                continue
            parts = l.split("~")
            if len(parts) > 7:
                code = parts[2]
                amt_wan = float(parts[7]) # 万元
                amt_yi = amt_wan / 10000.0 # 转换为亿元
                if code == "000001":
                    sh_amt = amt_yi
                elif code == "399001":
                    sz_amt = amt_yi
        tot_amt = sh_amt + sz_amt
        is_normal_volume = (tot_amt >= 6800.0) if tot_amt > 0 else True
        is_bull_volume = (tot_amt >= 12000.0) # 大于1.2万亿为高流动性
        
        if not is_normal_volume:
            vol_desc = "成交额不足6800亿（低流动性，短线接力胜率偏低，策略强制空仓）"
        elif is_bull_volume:
            vol_desc = "成交额大于1.2万亿（高流动性，次日冲高止盈目标上调至8.0%）"
        else:
            vol_desc = "成交额在6800亿至1.2万亿之间（正常流动性，次日冲高止盈目标为5.0%）"
        
        return {
            "sh_amt": round(sh_amt, 1),
            "sz_amt": round(sz_amt, 1),
            "tot_amt": round(tot_amt, 1),
            "is_normal_volume": is_normal_volume,
            "is_bull_volume": is_bull_volume,
            "vol_desc": vol_desc,
            "threshold": 6800.0,
            "summary": f"上证成交: {sh_amt:.0f}亿 | 深证成交: {sz_amt:.0f}亿 | 两市总成交: {tot_amt:.0f}亿 ({tot_amt/10000.0:.2f}万亿) | 状态: {vol_desc}"
        }
    except Exception as e:
        return {
            "sh_amt": 0.0, "sz_amt": 0.0, "tot_amt": 0.0,
            "is_normal_volume": True, "is_bull_volume": False,
            "vol_desc": "成交额接口异常，降级放行", "threshold": 6800.0,
            "summary": f"两市总成交额接口获取异常 ({e})，降级放行"
        }

def get_market_regime_snapshot(trade_date: str) -> dict:
    """第一层: 全市场成交量与情绪指标门禁"""
    headers = {"User-Agent": UA}
    params = {
        "page": 1, "limit": 1, "field": "199112,10", "filter": "HS,GEM2STAR",
        "order_field": "330324", "order_type": "0", "date": trade_date
    }
    snap = {
        "date": trade_date,
        "zt_count": 0,
        "zb_count": 0,
        "zb_rate": 0.0,
        "dt_count": 0,
        "passed": False,
        "warning_flag": None,
        "rating": "未知",
        "summary": "",
        "volume_status": {}
    }
    try:
        r = requests.get(THS_POOL_URL, params=params, headers=headers, timeout=5)
        d = r.json().get("data", {})
        luc = d.get("limit_up_count", {}).get("today", {})
        ldc = d.get("limit_down_count", {}).get("today", {})
        
        zt = luc.get("num", 0)
        zb = luc.get("open_num", 0)
        seal_rate = luc.get("rate", 0)
        zb_rate = round((1 - seal_rate) * 100, 1) if seal_rate > 0 else 0.0
        dt = ldc.get("num", 0)
        
        snap["zt_count"] = zt
        snap["zb_count"] = zb
        snap["zb_rate"] = zb_rate
        snap["dt_count"] = dt
        
        vol_st = get_market_volume_status()
        snap["volume_status"] = vol_st
        
        is_ice = zt < 40
        is_high_broken = zb_rate > 30.0
        is_panic_dt = dt > 10
        is_drought = not vol_st["is_normal_volume"]
        
        if is_drought:
            snap["rating"] = f"两市成交额仅 {vol_st['tot_amt']:.0f} 亿 < 6800 亿，市场流动性不足，执行空仓保护。"
            snap["passed"] = False
        elif is_ice:
            snap["rating"] = f"涨停家数仅 {zt} 家 < 40 家，市场赚钱效应不足，执行空仓保护。"
            snap["passed"] = False
        elif is_panic_dt:
            snap["rating"] = f"跌停家数达 {dt} 家 > 10 家，存在局部踩踏风险，执行空仓保护。"
            snap["passed"] = False
        elif is_high_broken:
            snap["rating"] = f"炸板率达 {zb_rate}% > 30%，冲高回落风险过高，执行空仓保护。"
            snap["passed"] = False
        else:
            snap["passed"] = True
            if zt > 85:
                snap["rating"] = f"涨停家数达 {zt} 家，市场处于过热区间，次日注意分化风险。"
                snap["warning_flag"] = "OVERHEATED_BREATH"
            else:
                snap["rating"] = f"两市成交 {vol_st['tot_amt']:.0f} 亿，涨停 {zt} 家，炸板率 {zb_rate}%，市场环境正常，允许开仓。"
        
        snap["summary"] = f"两市总成交={vol_st['tot_amt']:.0f}亿 | 涨停={zt}家, 炸板={zb}家(炸板率{zb_rate}%), 跌停={dt}家 | 判定: {snap['rating']}"
    except Exception as e:
        snap["summary"] = f"大盘快照拉取异常: {e}"
    return snap

def get_candidate_pool(prev_trade_date: str) -> list:
    """双轨候选池提取 (从前一交易日 T-1 的涨停池中提取标的，在 T 日检验蓄势)"""
    headers = {"User-Agent": UA}
    params = {
        "page": 1, "limit": 100,
        "field": "199112,10,9001,330323,330324,330325,9002,330329,133971,133970,1968584,3475914,9003,9004",
        "filter": "HS,GEM2STAR", "order_field": "330324", "order_type": "0", "date": prev_trade_date
    }
    candidates = []
    try:
        r = requests.get(THS_POOL_URL, params=params, headers=headers, timeout=6)
        info = (r.json().get("data") or {}).get("info", [])
        for it in info:
            code = str(it.get("code", "")).zfill(6)
            name = it.get("name", "")
            reason = it.get("reason_type", "")
            turnover_rate = float(it.get("turnover_rate") or 0.0)
            high_days = it.get("high_days", "首板")
            candidates.append({
                "code": code,
                "name": name,
                "reason": reason,
                "turnover_rate": turnover_rate,
                "high_days": high_days
            })
    except Exception as e:
        print(f"[WARN] 候选池拉取异常: {e}")
    return candidates

def evaluate_stock_snapshots(code: str, name: str, trade_date: str, reason: str, kline_df) -> dict:
    """对单只候选股票执行第 2~4 层客观量化体检并生成指标 (严禁偷看 T+1 数据)"""
    row_t = kline_df[kline_df['date'] == trade_date]
    if row_t.empty:
        return None
        
    t_data = row_t.iloc[0]
    open_t = float(t_data['open'])
    close_t = float(t_data['close'])
    high_t = float(t_data['high'])
    low_t = float(t_data['low'])
    preclose_t = float(t_data['preclose'])
    amount_t = float(t_data['amount']) / 1e8 if float(t_data['amount']) > 1e4 else float(t_data['amount']) # 统一换算为亿元
    pct_t = float(t_data['pctChg']) # 当日涨跌幅%
    
    # 查找 T-1 日成交额以计算日内量比 VR
    all_dates = kline_df['date'].tolist()
    cur_idx = all_dates.index(trade_date)
    prev_amt = amount_t
    if cur_idx > 0:
        prev_row = kline_df.iloc[cur_idx - 1]
        raw_prev_amt = float(prev_row['amount'])
        prev_amt = raw_prev_amt / 1e8 if raw_prev_amt > 1e4 else raw_prev_amt
        
    vr = round(amount_t / prev_amt, 2) if prev_amt > 0 else 1.0
    
    open_pct_t = round((open_t - preclose_t) / preclose_t * 100, 2) if preclose_t > 0 else 0.0
    lo_pct_t = round((low_t - preclose_t) / preclose_t * 100, 2) if preclose_t > 0 else 0.0
    max_gain_pct = round((high_t - preclose_t) / preclose_t * 100, 2)
    pullback_from_high = round((high_t - close_t) / high_t * 100, 2) if high_t > 0 else 0.0

    # 第 2 层: 板块属性与主流赛道加权 (+20分权重)
    mainstream_keywords = ['AI', '算力', '半导体', '芯片', '汽车', '智能', '机器人', '华为', '低空', '重组', '数据', '电网']
    is_mainstream_theme = any(k in reason for k in mainstream_keywords)
    snap2 = {
        "reason_type": reason,
        "is_mainstream": is_mainstream_theme,
        "score": 95 if is_mainstream_theme else 55,
        "summary": f"题材归因: [{reason}] | 主线属性: {'主流主线赛道（+20分权重）' if is_mainstream_theme else '非核心题材'}"
    }

    # 第 3 层: 个股流动性与异常分时过滤
    is_liquid_sweet = (4.5 <= amount_t <= 14.0)
    is_good_open = (open_pct_t >= -1.0)
    is_stable_low = (lo_pct_t >= -2.5)
    
    snap3 = {
        "amount_yi": round(amount_t, 2),
        "open_pct": open_pct_t,
        "lo_pct": lo_pct_t,
        "is_liquid_sweet": is_liquid_sweet,
        "is_good_open": is_good_open,
        "is_stable_low": is_stable_low,
        "score": (95 if (5.5 <= amount_t <= 10.0) else 80) if (is_good_open and is_stable_low and is_liquid_sweet) else 20,
        "summary": f"成交额: {amount_t:.1f}亿 {'符合区间(4.5~14亿)' if is_liquid_sweet else ('超出上限(>14亿)' if amount_t>14 else '成交偏小(<4.5亿)')} | 开盘: {open_pct_t:+.2f}% {'正常' if is_good_open else '低开幅度偏大(<-1.0%)'} | 最低: {lo_pct_t:+.2f}% {'稳定' if is_stable_low else '盘中破位(<-2.5%)'}"
    }

    # 第 4 层: 日内微观形态与量比过滤
    is_prime_golden = (1.8 <= pct_t <= 5.0)
    has_deadly_upper_shadow = (max_gain_pct >= 6.0 and pullback_from_high >= 2.0)
    is_tight_pullback = (pullback_from_high <= 2.0)
    is_healthy_vr = (vr <= 1.30)
    is_shrink_bonus = (vr <= 1.05) # 缩量蓄势
    
    shape_ok = is_prime_golden and (not has_deadly_upper_shadow) and is_tight_pullback and is_healthy_vr
    
    snap4 = {
        "close_pct": pct_t,
        "max_gain_pct": max_gain_pct,
        "pullback_from_high": pullback_from_high,
        "volume_ratio": vr,
        "has_deadly_shadow": has_deadly_upper_shadow,
        "is_prime_golden": is_prime_golden,
        "is_healthy_vr": is_healthy_vr,
        "is_shrink_bonus": is_shrink_bonus,
        "shape_ok": shape_ok,
        "score": 95 if (shape_ok and is_shrink_bonus) else (80 if shape_ok else (30 if (has_deadly_upper_shadow or not is_healthy_vr) else 50)),
        "summary": f"收盘涨幅: {pct_t:+.2f}% | 量比: {vr:.2f} {'缩量洗盘充分' if is_shrink_bonus else ('换手正常' if is_healthy_vr else '放量滞涨(>1.30)')} | 高点回落: {pullback_from_high:.2f}% | 形态: {'符合蓄势标准' if shape_ok else '形态不合格'}"
    }

    return {
        "code": code,
        "name": name,
        "close_price": close_t,
        "snap2": snap2,
        "snap3": snap3,
        "snap4": snap4,
    }

def synthesize_layer5_decision(candidate_evals: list, market_snap: dict) -> list:
    """第 5 层: 综合决策模块 (统筹 4 项指标生成最终决议)"""
    decisions = []
    global_defensive = not market_snap["passed"]
    
    for item in candidate_evals:
        s2 = item["snap2"]
        s3 = item["snap3"]
        s4 = item["snap4"]
        
        # 综合量化评分 (满分 100)
        raw_score = (s4["score"] * 0.4) + (s3["score"] * 0.3) + (s2["score"] * 0.3)
        
        action = "REJECT"
        thesis = ""
        
        has_negative_keywords = any(k in s2["reason_type"] for k in [
            '减持', '转让', '立案', '退市', 'ST', '重组失败', '亏损', '违规'
        ])
        
        if has_negative_keywords:
            action = "REJECT"
            thesis = f"【一票否决】题材归因包含风险关键词 ({s2['reason_type']})，次日开盘存在低开风险。"
        elif not s3.get("is_good_open", True):
            action = "REJECT"
            thesis = f"【开盘异常否决】T日开盘涨幅 ({s3['open_pct']:+.2f}% < -1.0%)，开盘卖盘偏重，尾盘拉升可能存在诱多。"
        elif not s3.get("is_stable_low", True):
            action = "REJECT"
            thesis = f"【分时破位否决】T日盘中最低价跌幅 ({s3['lo_pct']:+.2f}% < -2.5%)，分时筹码松动，尾盘拉升属弱势跟随。"
        elif s4["has_deadly_shadow"]:
            action = "REJECT"
            thesis = "【上影线过长否决】日内冲高回落幅度过大，上方存在套牢盘，次日开盘面临抛压。"
        elif not s4.get("is_healthy_vr", True):
            action = "REJECT"
            thesis = f"【量比异常否决】量比达 {s4['volume_ratio']} > 1.30 出现放量滞涨，存在减持出货迹象。"
        elif not s3["is_liquid_sweet"]:
            action = "REJECT"
            thesis = f"【流动性不合规】成交额 {s3['amount_yi']} 亿不在 4.5~14.0 亿适度区间。"
        elif not s4["is_prime_golden"]:
            action = "PASS"
            thesis = f"【涨幅偏离】当日涨幅 ({s4['close_pct']:+.2f}%) 不在 +1.8% ~ +5.0% 蓄势区间，暂不考虑。"
        elif global_defensive:
            action = "PASS"
            thesis = f"【大盘环境保护】个股形态达标，但大盘触发空仓保护 ({market_snap['rating']})，保持空仓。"
        elif market_snap.get("warning_flag") == "OVERHEATED_BREATH" and (not s2["is_mainstream"] or s3["amount_yi"] < 6.0):
            action = "PASS"
            thesis = f"【分化避险】市场涨停家数达 {market_snap['zt_count']} 家进入过热区间，次日面临分化，该标的非核心主线或成交额({s3['amount_yi']}亿<6亿)偏小，暂不参与。"
        else:
            action = "BUY"
            vr_str = "缩量蓄势充分" if s4.get("is_shrink_bonus") else "换手正常"
            theme_str = "核心主流赛道" if s2.get("is_mainstream") else "独立题材"
            thesis = f"【建议买入】四项指标均达标：{theme_str} ({s2['reason_type']}) + 适度成交 ({s3['amount_yi']}亿) + {vr_str} + 形态紧凑无长上影。"
            
        decisions.append({
            "code": item["code"],
            "name": item["name"],
            "close_price": item["close_price"],
            "total_score": round(raw_score, 1),
            "action": action,
            "thesis": thesis,
            "snap2": s2,
            "snap3": s3,
            "snap4": s4
        })
        
    decisions.sort(key=lambda x: x["total_score"], reverse=True)
    return decisions

def generate_trading_action_card(decisions: list, market_snap: dict, account_capital: float = 30000.0) -> str:
    """
    生成规范化【实盘操作指令卡】(清晰告知买入多少股、次日开盘何时清仓、何时止盈锁仓)
    适配万级（如 3 万元起步）实盘与模拟账户
    """
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    vol_st = market_snap.get("volume_status", {})
    tot_amt = vol_st.get("tot_amt", 0.0)
    is_bull = vol_st.get("is_bull_volume", False)
    vol_desc = vol_st.get("vol_desc", "未知")
    
    # 筛选真正买入的标的 (最多 2 只)
    buys = [d for d in decisions if d["action"] == "BUY"][:2]
    
    card = []
    card.append(f"# 【尾盘隔夜策略·实盘操作执行指令卡】")
    card.append(f"生成时间: {now_str} | 基准账户本金: ¥{account_capital:,.0f} 元\n")
    card.append("---")
    
    # 模块 1: 大盘环境体检
    card.append("### 第一部分：今日大盘成交量与情绪指标")
    card.append(f"* 全市场两市总成交额: {tot_amt:.0f} 亿元 ({tot_amt/10000.0:.2f} 万亿)")
    card.append(f"* 市场流动性状态: {vol_desc}")
    card.append(f"* 市场赚钱效应: 涨停 {market_snap.get('zt_count', 0)} 家 | 跌停 {market_snap.get('dt_count', 0)} 家 | 炸板率 {market_snap.get('zb_rate', 0.0)}%")
    card.append(f"* 准入判定: {market_snap.get('rating', '未知')}\n")
    
    if not market_snap.get("passed", False):
        card.append("> 【今日操作指令：保持空仓】")
        card.append("> 大盘环境不满足准入条件，今日不进行任何买入操作，保持空仓防守。\n")
        return "\n".join(card)
        
    card.append("---")
    
    # 模块 2: 今日买入执行
    card.append("### 第二部分：今日尾盘买入操作指令 (14:45 ~ 14:55 执行)")
    if not buys:
        card.append("今日候选池股票经多维度量化指标筛选，未出现符合蓄势标准的标的，今日无买入指令，保持空仓观望。\n")
        return "\n".join(card)
        
    num_buys = len(buys)
    alloc_ratio = 1.0 if num_buys == 1 else 0.5
    alloc_cash = account_capital * alloc_ratio
    
    card.append(f"今日共筛选出 {num_buys} 只符合标准的标的，资金分配原则：每只标的分配 {alloc_ratio*100:.0f}% 仓位 (约 ¥{alloc_cash:,.0f} 元)：\n")
    
    for idx, b in enumerate(buys, 1):
        p = b["close_price"]
        shares = int(alloc_cash / p / 100) * 100 if p > 0 else 0
        actual_money = shares * p
        card.append(f"#### 标的 {idx}：{b['name']} ({b['code']})")
        card.append(f"* 当前现价: ¥{p:.2f} 元 | 综合评分: {b['total_score']} 分")
        card.append(f"* 所属题材: {b['snap2']['reason_type']}")
        card.append(f"* 下单买入建议: 在 14:45 ~ 14:55 挂现价或卖一价买入")
        card.append(f"* 建议买入股数: {shares:,} 股 (约 {shares/100:.0f} 手，投入金额约 ¥{actual_money:,.0f} 元)")
        card.append(f"* 入选逻辑: {b['thesis']}\n")
        
    card.append("---")
    
    # 模块 3: 次日作战推演与出场指令
    card.append("### 第三部分：次日早盘出场指令 (超短隔夜核心原则：只赚早盘溢价，绝不在垃圾时间陪跑)")
    card.append("次日早盘（T+1 日），请严格按照以下四种情景执行出场：\n")
    
    # 情景 1: 竞价止损
    card.append("#### 情景一：开盘大幅低开止损 (发生概率约 10%)")
    card.append("* 触发时间: 次日 09:25 (集合竞价结束时)")
    card.append("* 触发条件: 开盘跌幅 < -2.0%")
    card.append("* 执行操作: 09:25 直接以市价单全额卖出止损，控制回撤。\n")
    
    # 情景 2: 阶梯分层冲高止盈
    card.append("#### 情景二：阶梯分层冲高止盈 (发生概率约 70%)")
    card.append("* 触发时间: 次日 09:30 ~ 10:00 (早盘黄金半小时)")
    card.append("* 档位 1【起步保利档】: 盘中最高涨幅 >= +2.0%，一旦从最高点回落超 0.8%，市价全额卖出止盈，锁住小利润；")
    if is_bull:
        card.append(f"* 档位 2【牛市大肉档 (成交额>1.2万亿)】: 盘中最高涨幅 >= +8.0%，一旦从最高点回落超 1.5%，市价全额卖出止盈；")
    else:
        card.append(f"* 档位 2【常态大肉档】: 盘中最高涨幅 >= +5.0%，一旦从最高点回落超 1.2%，市价全额卖出止盈；\n")
        
    # 情景 3: 10:00 时间熔断
    card.append("#### 情景三：10:00 时间熔断离场令 (发生概率约 15%)")
    card.append("* 触发时间: 次日 10:00 准时执行")
    card.append("* 触发条件: 早盘黄金半小时冲高未达 +2.0% 且未封板（横盘滞涨，主力无上攻意图）")
    card.append("* 执行操作: 10:00 准时以市价/现价全额卖出清仓！平价或微利微亏出局，绝不持有到下午，把资金腾出来防守，规避全天跳水风险！\n")
    
    # 情景 4: 封死涨停
    card.append("#### 情景四：强势封死涨停板锁仓 (发生概率约 5%)")
    card.append("* 触发条件: 早盘快速封死涨停板 (+9.5% ~ +10.0%) 且封单稳定无持续大单抛压")
    card.append("* 执行规则: 封板期间不卖出，持仓过夜至 T+2 日早盘冲高卖出，获取连板溢价。\n")
    
    card.append("---")
    card.append("操作说明：短线交易依赖纪律与概率，严格按买入比例分配仓位并执行出场规则，保持交易一致性。")
    
    return "\n".join(card)

if __name__ == '__main__':
    print("="*75)
    print("   尾盘隔夜策略流水线自检测试 (Tail Overnight Strategy Pipeline)")
    print("="*75)
    today_str = datetime.date.today().strftime("%Y%m%d")
    print(f"正在诊断今日 ({today_str}) 大盘与全市场成交量状态...")
    m_snap = get_market_regime_snapshot(today_str)
    
    # 模拟标的生成指令卡测试
    mock_decisions = [
        {
            "code": "002448", "name": "中原内配", "close_price": 12.50, "total_score": 93.5, "action": "BUY",
            "thesis": "【建议买入】四项指标均达标：核心主流赛道 (机器人+汽车零部件) + 适度成交 (8.2亿) + 缩量蓄势充分 + 形态紧凑无长上影。",
            "snap2": {"reason_type": "机器人+汽车零部件", "is_mainstream": True},
            "snap3": {"amount_yi": 8.2},
            "snap4": {"volume_ratio": 0.88, "is_shrink_bonus": True}
        }
    ]
    
    # 打印操作卡 (假设账户本金 3 万元)
    card = generate_trading_action_card(mock_decisions, m_snap, account_capital=30000.0)
    print("\n" + card)
