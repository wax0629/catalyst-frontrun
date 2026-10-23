#!/usr/bin/env python3
"""
双层量化基本面筛选与门禁验证器 (Two-Layer Quantamental Screener)

核心逻辑：
第一层（催化与预期差）：
- 筛选具有国家部委政策、中央流动性、全球突发事件等实质利好催化的标的；
- 门禁一：是否处于涨幅 < +2.5% 的 T0 静默萌芽期？（杜绝后视镜追涨）。

第二层（量化指标刚性把关）：
- 门禁二：5 日反转因子排雷（近 5 日累计涨幅必须 < 15%，排除短期过热竭尽标的）；
- 门禁三：主力资金 Q 因子（全天成交额满足龙头门槛，证明有机构大资金隐蔽承接）；
- 门禁四：均线支撑结构（股价回踩或企稳于 MA5 / MA20 关键生命线）；
- 门禁五：盈亏比评估（预期涨幅 / 潜在止损空间 >= 2.0）。
"""

import sys
import argparse

def evaluate_candidate(name, code, current_price, catalyst_desc, day_gain_pct, five_day_gain_pct, turnover_yi, ma5, ma20, stop_price, target_price):
    print("=" * 65)
    print(f" 🔍 标的评估: {name} ({code})")
    print(f" 催化描述: {catalyst_desc}")
    print("=" * 65)

    passed = True
    reasons = []

    # 1. 萌芽期静默门禁
    print(f"[1/5] 日内涨幅静默检验: 当日涨幅 {day_gain_pct:+.2f}%")
    if day_gain_pct > 3.0:
        passed = False
        reasons.append(f"日内涨幅过高 (+{day_gain_pct:.2f}% > +3.0%)，散户已开始跟风，丧失 T0 静默先发优势")
        print("  ❌ 未通过: 丧失萌芽静默期优势")
    else:
        print("  ✅ 通过: 处于 T0 萌芽静默期，成本极低")

    # 2. 5日反转排雷
    print(f"[2/5] 5日反转因子排雷: 近5日涨幅 {five_day_gain_pct:+.2f}%")
    if five_day_gain_pct > 15.0:
        passed = False
        reasons.append(f"近5日涨幅超买 (+{five_day_gain_pct:.2f}% > +15.0%)，极易遭遇高位补跌或兑现砸盘（如日发精机案例）")
        print("  ❌ 未通过: 触发短期反转过热排雷")
    else:
        print("  ✅ 通过: 无过度炒作泡沫，反转因子安全")

    # 3. 主力资金成交额门禁
    print(f"[3/5] 主力资金 Q 因子: 当日成交额 {turnover_yi:.2f} 亿元")
    if turnover_yi < 3.0:
        passed = False
        reasons.append(f"成交额过低 ({turnover_yi:.2f} 亿 < 3.0 亿)，缺乏机构与大资金深度承接")
        print("  ❌ 未通过: 流动性不足")
    else:
        print("  ✅ 通过: 大资金深沉，抗跌承接力强")

    # 4. 均线支撑结构
    print(f"[4/5] 均线形态评估: 现价 {current_price:.2f} 元 | MA5={ma5:.2f} | MA20={ma20:.2f}")
    if current_price < min(ma5, ma20) * 0.985:
        passed = False
        reasons.append(f"现价击穿关键均线支撑 ({current_price:.2f} < MA5/MA20)")
        print("  ❌ 未通过: 技术形态破位")
    else:
        print("  ✅ 通过: 处于 MA5/MA20 强势支撑带上方")

    # 5. 盈亏比评估
    potential_loss = abs((current_price - stop_price) / current_price) * 100.0
    potential_gain = ((target_price - current_price) / current_price) * 100.0
    rr_ratio = potential_gain / potential_loss if potential_loss > 0 else 0.0

    print(f"[5/5] 盈亏比核算: 止损位 {stop_price:.2f} (-{potential_loss:.1f}%) | 目标位 {target_price:.2f} (+{potential_gain:.1f}%)")
    print(f"      计算盈亏比: {rr_ratio:.2f} : 1.00 (标准 >= 2.0)")

    if potential_loss > 4.5:
        passed = False
        reasons.append(f"初始止损空间过大 (-{potential_loss:.1f}% > -4.5%)，超出单笔刚性风控上限")
        print("  ❌ 未通过: 止损空间超过 4.5% 硬约束")
    elif rr_ratio < 2.0:
        passed = False
        reasons.append(f"盈亏比不达标 ({rr_ratio:.2f} < 2.0)")
        print("  ❌ 未通过: 盈亏比不足")
    else:
        print("  ✅ 通过: 盈亏比优秀，风险可控")

    print("-" * 65)
    if passed:
        print(f"🎉 综合决策结论: 【BUY / 允许建仓】 — 建议仓位 15%~20% 试仓。")
    else:
        print(f"🛑 综合决策结论: 【REJECT / 门禁否决】 — 原因: {'; '.join(reasons)}。")
    print("=" * 65 + "\n")

    return passed

if __name__ == "__main__":
    # 演示案例：10-22 均胜电子 vs 日发精机 门禁对比
    print("【历史经典案例回溯校验】\n")
    evaluate_candidate(
        name="均胜电子", code="600699", current_price=20.85,
        catalyst_desc="工信部宣布开展第二批L3自动驾驶试点",
        day_gain_pct=1.00, five_day_gain_pct=4.20, turnover_yi=13.65,
        ma5=20.80, ma20=19.90, stop_price=20.20, target_price=23.00
    )

    evaluate_candidate(
        name="日发精机", code="002520", current_price=6.10,
        catalyst_desc="工业母机与减速器概念跟风",
        day_gain_pct=8.50, five_day_gain_pct=26.30, turnover_yi=3.20,
        ma5=5.80, ma20=5.40, stop_price=5.60, target_price=6.50
    )
