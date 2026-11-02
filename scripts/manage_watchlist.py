#!/usr/bin/env python3
"""
动态标的注册表与生命周期流转管理器 (Dynamic Watchlist & Lifecycle Registry Manager)

定位：
彻底告别硬编码死代码，为【双层量化基本面·催化抢跑体系】提供标准化的三层标的生命周期动态流转能力。

标的生命周期池 (Four-Tier Lifecycle Pools):
1. [active_holdings] 实盘当前持仓池 (0~2 只，严格执行 1% 账户风险预算)
2. [track1_candidates] T0 政策萌芽前瞻池 (实时注入，48 小时未触发自动老化)
3. [track2_reserves] 战略进攻储备池 (按月度/重大宏观事件轮动，如 11 月 Anthropic IPO 算力链)
4. [archived_cases] 历史复盘与闭环归档池 (止盈/止损出局后沉淀复盘教训，不参与日常盯盘)

支持 CLI 操作：
  python scripts/manage_watchlist.py list
  python scripts/manage_watchlist.py add_t1 <code> <name> <thesis> <support> <target>
  python scripts/manage_watchlist.py add_t2 <code> <name> <sector> <support> <target> <thesis> [earnings]
  python scripts/manage_watchlist.py promote_holding <code> <cost>
  python scripts/manage_watchlist.py archive <code> <exit_price> <net_return> <status> <post_mortem>
  python scripts/manage_watchlist.py remove <code>
"""

import sys
import os
import json
import datetime

REGISTRY_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "watchlist_registry.json")

def load_registry():
    if not os.path.exists(REGISTRY_PATH):
        return {
            "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S CST"),
            "active_holdings": [],
            "track1_candidates": [],
            "track2_reserves": [],
            "archived_cases": []
        }
    with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_registry(data):
    data["updated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S CST")
    os.makedirs(os.path.dirname(REGISTRY_PATH), exist_ok=True)
    with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def list_watchlist():
    reg = load_registry()
    print("=" * 80)
    print(f" 📋 双层量化基本面 · 动态标的生命周期看板 (更新时间: {reg.get('updated_at')})")
    print("=" * 80)

    print("\n【1. 当前活跃实盘持仓池 (Active Holdings · 0~2 只)】")
    if not reg.get("active_holdings"):
        print("  • 当前无持仓 (100% 现金绝对防守状态)")
    else:
        for h in reg["active_holdings"]:
            print(f"  🎯 [{h['name']}] ({h['code']}): 成本 {h['cost']}元 | 止损 {h['stop_loss']}元 | 目标 {h['target']}元 | 入场时间: {h['entry_date']}")

    print("\n【2. Track 1 动态政策前瞻候选池 (T0 Ingestion · 48小时生命周期)】")
    if not reg.get("track1_candidates"):
        print("  • 当前无触发标的 (Track 1 严格为空)")
    else:
        for c in reg["track1_candidates"]:
            print(f"  🔍 [{c['name']}] ({c['code']}): 催化线索: {c['thesis']} | 支撑 {c['support']}元 | 目标 {c['target']}元 | 注入时间: {c['added_date']}")

    print("\n【3. Track 2 宏观战略进攻储备池 (Thematic Reserves · 动态轮动)】")
    if not reg.get("track2_reserves"):
        print("  • 储备池为空")
    else:
        for r in reg["track2_reserves"]:
            print(f"  ⭐ [{r['name']}] ({r['code']}): {r['sector']} | 支撑: {r['support']}元 | 目标: {r['target']}元")
            print(f"     逻辑: {r['thesis']}")
            print(f"     财报: {r.get('earnings_summary', '暂无')}")

    print("\n【4. 历史战役闭环归档池 (Archived Cases)】")
    for a in reg.get("archived_cases", []):
        print(f"  📦 [{a.get('case_id')}] {a['name']} ({a['code']}): 结局 {a['status']} | 净收益率 {a['net_return']} | 复盘: {a['post_mortem']}")
    print("=" * 80 + "\n")

def add_t1_candidate(code, name, thesis, support, target):
    reg = load_registry()
    reg["track1_candidates"] = [x for x in reg["track1_candidates"] if x["code"] != code]
    reg["track1_candidates"].append({
        "code": code,
        "name": name,
        "thesis": thesis,
        "support": float(support),
        "target": float(target),
        "added_date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    })
    save_registry(reg)
    print(f"✅ 成功将 [{name} ({code})] 注入 Track 1 动态政策前瞻池。")

def add_t2_reserve(code, name, sector, support, target, thesis, earnings=""):
    reg = load_registry()
    reg["track2_reserves"] = [x for x in reg["track2_reserves"] if x["code"] != code]
    reg["track2_reserves"].append({
        "code": code,
        "name": name,
        "sector": sector,
        "support": float(support),
        "target": float(target),
        "thesis": thesis,
        "earnings_summary": earnings,
        "added_date": datetime.datetime.now().strftime("%Y-%m-%d")
    })
    save_registry(reg)
    print(f"✅ 成功将 [{name} ({code})] 纳入 Track 2 战略进攻储备池。")

def promote_to_holding(code, cost, stop_loss, target):
    reg = load_registry()
    # Find candidate
    found = None
    for pool_name in ["track1_candidates", "track2_reserves"]:
        for item in reg[pool_name]:
            if item["code"] == code:
                found = item
                reg[pool_name].remove(item)
                break
        if found:
            break
    
    name = found["name"] if found else code
    thesis = found.get("thesis", "") if found else ""
    reg["active_holdings"].append({
        "code": code,
        "name": name,
        "cost": float(cost),
        "stop_loss": float(stop_loss),
        "target": float(target),
        "thesis": thesis,
        "entry_date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    })
    save_registry(reg)
    print(f"🚀 标的 [{name} ({code})] 正式转为实盘持仓池 (成本: {cost} 元)。")

def archive_case(code, exit_price, net_return, status, post_mortem):
    reg = load_registry()
    holding = None
    for h in reg["active_holdings"]:
        if h["code"] == code:
            holding = h
            reg["active_holdings"].remove(h)
            break
    
    name = holding["name"] if holding else code
    case_num = len(reg.get("archived_cases", [])) + 1
    reg["archived_cases"].append({
        "case_id": f"CASE-{case_num:02d}",
        "code": code,
        "name": name,
        "exit_price": float(exit_price),
        "net_return": net_return,
        "status": status,
        "exit_date": datetime.datetime.now().strftime("%Y-%m-%d"),
        "post_mortem": post_mortem
    })
    save_registry(reg)
    print(f"📦 标的 [{name} ({code})] 已完成闭环归档 (结局: {status}, 收益: {net_return})。")

def remove_symbol(code):
    reg = load_registry()
    for pool in ["active_holdings", "track1_candidates", "track2_reserves"]:
        reg[pool] = [x for x in reg[pool] if x["code"] != code]
    save_registry(reg)
    print(f"🗑️ 已从所有活跃监控池中移除 [{code}]。")

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] == "list":
        list_watchlist()
    elif sys.argv[1] == "add_t1" and len(sys.argv) >= 7:
        add_t1_candidate(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6])
    elif sys.argv[1] == "add_t2" and len(sys.argv) >= 8:
        earnings = sys.argv[8] if len(sys.argv) > 8 else ""
        add_t2_reserve(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6], sys.argv[7], earnings)
    elif sys.argv[1] == "promote" and len(sys.argv) >= 6:
        promote_to_holding(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5])
    elif sys.argv[1] == "archive" and len(sys.argv) >= 7:
        archive_case(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6])
    elif sys.argv[1] == "remove" and len(sys.argv) >= 3:
        remove_symbol(sys.argv[2])
    else:
        print("用法:")
        print("  python scripts/manage_watchlist.py list")
        print("  python scripts/manage_watchlist.py add_t1 <代码> <名称> <逻辑> <支撑> <目标>")
        print("  python scripts/manage_watchlist.py add_t2 <代码> <名称> <板块> <支撑> <目标> <逻辑> [财报]")
        print("  python scripts/manage_watchlist.py promote <代码> <买入均价> <止损价> <目标价>")
        print("  python scripts/manage_watchlist.py archive <代码> <平仓价> <收益率> <状态> <复盘教训>")
        print("  python scripts/manage_watchlist.py remove <代码>")
