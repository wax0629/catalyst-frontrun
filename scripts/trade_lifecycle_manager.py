#!/usr/bin/env python3
"""
交易生命周期与动态止盈止损管理器 (Trade Lifecycle & Trailing Stop Manager)

管理四阶段生命周期：
1. T0 阶段：潜伏锁定，底仓 15%，设置 -3.0%~-4.5% 硬止损；
2. T1 阶段：脱离成本区（浮盈 > +3%），立即启动保本锁（Break-Even Stop），提升止损至成本线上方；
3. T2~T5 阶段：主升加速，启用动态吊灯止盈（Trailing Stop，从日内高点回落设定比例锁定浮盈）；
4. T5~T10 阶段：利好事实兑现或触及目标位，全额止盈落袋；
5. 时间止损（Time Stop）：若持股 5 个交易日预期未发酵且股价未动，无条件平仓换仓。
"""

import sys
import datetime

class PositionLifecycle:
    def __init__(self, symbol, name, entry_date, entry_price, shares, initial_stop, target_price):
        self.symbol = symbol
        self.name = name
        self.entry_date = datetime.datetime.strptime(entry_date, "%Y-%m-%d").date()
        self.entry_price = entry_price
        self.shares = shares
        self.initial_stop = initial_stop
        self.current_stop = initial_stop
        self.target_price = target_price
        self.highest_price = entry_price

    def update_price(self, current_date_str, current_price, intraday_high):
        curr_date = datetime.datetime.strptime(current_date_str, "%Y-%m-%d").date()
        holding_days = (curr_date - self.entry_date).days
        self.highest_price = max(self.highest_price, intraday_high)

        pnl_pct = ((current_price - self.entry_price) / self.entry_price) * 100.0
        max_pnl_pct = ((self.highest_price - self.entry_price) / self.entry_price) * 100.0

        # 动态风控状态机推进
        stage = "T0 潜伏期"
        action = "持有待发酵"

        # 规则 1：时间止损门槛
        if holding_days >= 5 and pnl_pct < 2.0:
            stage = "时间熔断阶段"
            action = "⚠️ 已达 5 天时间止损窗口，题材未催化，建议收盘前平价或微亏出局换仓！"

        # 规则 2：目标位触及
        elif current_price >= self.target_price:
            stage = "T5~T10 目标达成期"
            action = "🎯 已触及目标价格区间，散户情绪高潮，建议全额分批清仓止盈！"

        # 规则 3：主升脱离成本区（移动止盈机制）
        elif max_pnl_pct >= 6.0:
            stage = "T2~T5 主升加速期"
            # 吊灯止盈：从最高点回撤不超过 2.5%
            trailing_stop = self.highest_price * 0.975
            self.current_stop = max(self.current_stop, trailing_stop, self.entry_price * 1.015)
            if current_price < self.current_stop:
                action = f"🛑 触及移动止盈线 ({self.current_stop:.2f} 元)，锁定利润离场！"
            else:
                action = f"🚀 移动止盈线上移至 {self.current_stop:.2f} 元，底仓锁盈继续奔跑。"

        # 规则 4：脱离成本区（保本保护机制）
        elif pnl_pct >= 3.0:
            stage = "T1 脱离成本期"
            self.current_stop = max(self.current_stop, self.entry_price * 1.005) # 锁死保本
            action = f"🛡️ 已启动保本锁（防守线上移至 {self.current_stop:.2f} 元），彻底消除本金亏损可能。"

        # 规则 5：硬止损跌破
        elif current_price <= self.current_stop:
            stage = "破位止损期"
            action = f"❌ 跌破初始硬止损线 ({self.current_stop:.2f} 元)，执行纪律斩仓！"

        return {
            "symbol": self.symbol,
            "name": self.name,
            "holding_days": holding_days,
            "current_price": current_price,
            "entry_price": self.entry_price,
            "highest_price": self.highest_price,
            "current_pnl_pct": pnl_pct,
            "max_pnl_pct": max_pnl_pct,
            "current_stop": self.current_stop,
            "stage": stage,
            "action": action,
        }

if __name__ == "__main__":
    print("=" * 70)
    print(" 📊 持仓生命周期与动态止盈止损演变演示")
    print("=" * 70)

    # 案例演示：均胜电子从 10-22 到 10-23 的生命周期演化
    pos = PositionLifecycle(
        symbol="600699", name="均胜电子",
        entry_date="2026-10-22", entry_price=20.85, shares=1000,
        initial_stop=20.20, target_price=23.00
    )

    print("\n【状态演变 1：10-22 建仓收盘】")
    res1 = pos.update_price("2026-10-22", current_price=20.79, intraday_high=21.17)
    print(f"阶段: {res1['stage']} | 现价: {res1['current_price']:.2f} | 盈亏: {res1['current_pnl_pct']:+.2f}% | 止损线: {res1['current_stop']:.2f} | 建议: {res1['action']}")

    print("\n【状态演变 2：10-23 午后爆发 冲高至 22.55】")
    res2 = pos.update_price("2026-10-23", current_price=22.23, intraday_high=22.55)
    print(f"阶段: {res2['stage']} | 现价: {res2['current_price']:.2f} | 盈亏: {res2['current_pnl_pct']:+.2f}% | 止损线: {res2['current_stop']:.2f} | 建议: {res2['action']}")

    print("\n" + "=" * 70)
