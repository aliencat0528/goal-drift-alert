"""期望損失 V 與可救性。

    V = P(風險為真) × 未處理損失 × 剩餘可行動時間比例 × 可救性 − 打斷成本

四項相乘的意思是**任何一項為零，這則就不該發**：
沒風險不發、沒損失不發、沒時間可行動不發、救不回來也不發（改發建議改目標）。
"""

from __future__ import annotations

from dataclasses import dataclass

from compute.forecast import Forecast
from compute.metrics import GoalMetrics
from core.config import Params


@dataclass
class ValueBreakdown:
    """V 的完整拆解。逃生出口之三是「看見完整推導」，所以每一項都要留得下來。"""

    p_risk: float
    loss: float
    loss_basis: str
    time_ratio: float
    salvageability: float
    interrupt_cost: float
    value: float
    stake: float

    def as_lines(self) -> list[str]:
        return [
            f"P(風險為真) = {self.p_risk:.2f}",
            f"未處理損失 = {self.loss:.2f}（{self.loss_basis}）",
            f"剩餘可行動時間比例 = {self.time_ratio:.2f}",
            f"可救性 = {self.salvageability:.2f}",
            f"打斷成本 = {self.interrupt_cost:.2f}",
            f"V = {self.p_risk:.2f} × {self.loss:.2f} × {self.time_ratio:.2f} × "
            f"{self.salvageability:.2f} − {self.interrupt_cost:.2f} = {self.value:.2f}",
        ]


def salvageability(metrics: GoalMetrics, params: Params) -> float:
    """可救性：required rate 還在不在你的能力範圍內。

        = 1                    required ≤ 歷史最佳 P90
        = 線性遞減              介於兩者之間
        = 0（改發建議改目標）    required > 歷史最佳 × infeasible_multiple

    沒有這一項，系統會在最後三天每天提醒你一件已經做不到的事——
    那是最典型、也最快讓人關掉通知的失敗模式。
    """
    if metrics.required_rate is None or metrics.gap <= 0:
        return 0.0
    best = metrics.hist_best_rate
    if not best or best <= 0:
        # 還沒有足夠歷史可以說「你做不到」。此時不主張不可能，交給資料不足的關卡去擋
        return 1.0

    ceiling = best * float(params.drift.infeasible_multiple)
    if metrics.required_rate <= best:
        return 1.0
    if metrics.required_rate >= ceiling:
        return 0.0
    return float((ceiling - metrics.required_rate) / (ceiling - best))


def expected_loss(metrics: GoalMetrics, forecast: Forecast, params: Params) -> tuple[float, str]:
    """未處理損失。有金額走金額，沒金額走注意力單位。

    注意力單位的定義寫在 `gate.interrupt_only_loss_units`：
    「錯過整個目標大約等於幾次打斷的代價」。這個數字決定了 V 的尺度，
    `min_value` 與 `interrupt_cost` 都以它為單位——**改它等於改全系統的靈敏度**。
    """
    goal = metrics.goal
    if forecast.ready and forecast.expected_final is not None:
        shortfall = max(goal.target - forecast.expected_final, 0.0)
        basis = "預期缺口取 Monte Carlo 期末平均"
    else:
        shortfall = metrics.gap
        basis = "預期缺口取目前缺口（預測校準中）"

    if goal.has_money():
        return shortfall * float(goal.unit_value), f"{basis} × unit_value"

    units = float(params.gate.interrupt_only_loss_units)
    ratio = shortfall / goal.target if goal.target else 0.0
    return units * ratio, f"{basis}／target × interrupt_only 基準 {units:g}"


def fallback_risk(metrics: GoalMetrics) -> float:
    """沒有 Monte Carlo 時的 P(風險為真) 替代值：`1 − 目前速度 ÷ required`。

    意思是「照現在的速度只能蓋掉 required 的幾成」。它比「缺口 ÷ target」誠實得多——
    後者在期初就會給出一個嚇人的數字，而期初缺口大是正常的，不是風險。
    """
    if metrics.gap <= 0:
        return 0.0
    if not metrics.required_rate or metrics.required_rate <= 0:
        return 0.0
    return float(min(max(1 - metrics.run_rate / metrics.required_rate, 0.0), 1.0))


def compute_value(
    metrics: GoalMetrics, forecast: Forecast, params: Params, p_risk: float | None
) -> ValueBreakdown:
    """算出這則候選的 V。`p_risk` 為 None（預測校準中）時走 `fallback_risk`。"""
    if p_risk is None:
        p_risk = fallback_risk(metrics)

    loss, basis = expected_loss(metrics, forecast, params)
    time_ratio = metrics.remaining_time_ratio
    salvage = salvageability(metrics, params)
    interrupt_cost = float(params.gate.interrupt_cost)

    value = p_risk * loss * time_ratio * salvage - interrupt_cost
    # stake：把可救性拿掉的「賭注大小」。可救性歸零的目標 V 必為負，
    # 但「建議改目標」這張卡仍要排序——排的就是這個賭注
    stake = p_risk * loss * time_ratio - interrupt_cost

    return ValueBreakdown(
        p_risk=p_risk,
        loss=loss,
        loss_basis=basis,
        time_ratio=time_ratio,
        salvageability=salvage,
        interrupt_cost=interrupt_cost,
        value=value,
        stake=stake,
    )
