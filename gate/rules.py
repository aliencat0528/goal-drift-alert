"""三個不該警示的時刻，加上冷啟動分級。

這些規則寫在 gate 裡而不是靠人記得，是整個設計的重點之一：
**期初、剛達成里程碑後、只是落後**——這三種情況下發出的警示全都是「正確但沒用」，
而沒用的警示消耗的信任與有用的警示一樣多。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np

from compute.detect import Candidate
from compute.metrics import GoalMetrics
from core.config import Params

# 各階段的意思見 docs/DECISION-FLOW.md 五道關卡（關卡 3／4）
STAGE_OBSERVE = "observe"
STAGE_SHADOW = "shadow"
STAGE_RAMP_UP = "ramp_up"
STAGE_FULL = "full"

STAGE_LABELS = {
    STAGE_OBSERVE: "觀察期（只收不發）",
    STAGE_SHADOW: "影子模式（寫進報表但不推播）",
    STAGE_RAMP_UP: "分級發布（只發最高分的）",
    STAGE_FULL: "正常發布",
}


@dataclass
class Stage:
    name: str
    day_index: int
    quota: int
    deliver: bool

    @property
    def label(self) -> str:
        return STAGE_LABELS[self.name]


def resolve_stage(system_start: date | None, as_of: date, params: Params) -> Stage:
    """系統上線第幾天了，今天能發幾則。

    分級發布不是保守，是**讓誤報在便宜的時候暴露出來**：
    第一天就開滿配額，第一則誤報就會用掉使用者對系統的信任額度。
    """
    quota = int(params.gate.daily_quota)
    if system_start is None:
        return Stage(STAGE_OBSERVE, 0, 0, False)

    day_index = (as_of - system_start).days + 1
    observe = int(params.cold_start.observe_days)
    shadow = int(params.cold_start.shadow_days)
    ramp_up = int(params.cold_start.ramp_up_days)

    if day_index <= observe:
        return Stage(STAGE_OBSERVE, day_index, 0, False)
    if day_index <= observe + shadow:
        return Stage(STAGE_SHADOW, day_index, quota, False)
    if day_index <= observe + shadow + ramp_up:
        return Stage(STAGE_RAMP_UP, day_index, int(params.cold_start.ramp_up_quota), True)
    return Stage(STAGE_FULL, day_index, quota, True)


def suppression_reason(
    candidate: Candidate, metrics: GoalMetrics, params: Params
) -> tuple[str, str] | None:
    """該不該閉嘴。回傳 (代碼, 給人看的理由) 或 None。"""
    goal = metrics.goal

    if metrics.closed:
        return "goal_closed", f"目標期間已於 {goal.deadline} 結束，這是結果不是風險"
    if metrics.gap <= 0:
        return "already_met", f"已達成（{metrics.cumulative:g}／{goal.target:g}）"

    early = float(params.gate.early_period_ratio)
    if metrics.elapsed_ratio < early:
        return "early_period", f"時間才過 {metrics.elapsed_ratio:.0%}，未達 {early:.0%}，太早"

    milestone = _recent_milestone(metrics, params)
    if milestone is not None and candidate.trigger in ("trend_reversal", "silence"):
        days, value = milestone
        return "post_milestone", f"{days} 天前才做了 {value:g}（超過自己的 P75），短期速率天然會掉"

    # 「只是落後」不需要打斷你，「不可能」才需要。可行性翻轉本身就是在說不可能，故不受此條約束
    if candidate.trigger != "feasibility_flip" and metrics.hist_best_rate:
        if metrics.required_rate is not None and metrics.required_rate <= metrics.hist_best_rate:
            return (
                "just_behind",
                f"required {metrics.required_rate:.2f}／天仍在歷史正常範圍內"
                f"（≤ P90 {metrics.hist_best_rate:.2f}）",
            )

    # 預測校準中**不擋警示**：資料量門檻是「該偵測器能不能用」，不是「這則能不能發」。
    # D4 靠歷史最佳 P90（min_points.historical_best）、D5 靠 EWMA 的點數，各自在偵測層就擋掉了；
    # Monte Carlo 不足只影響卡片上的機率數字，那時卡片會直接寫「預測校準中」而不是印一個假機率
    return None


def _recent_milestone(metrics: GoalMetrics, params: Params) -> tuple[int, float] | None:
    """近幾天有沒有一次超過自己 P75 的產出。"""
    days = int(params.gate.post_milestone_days)
    percentile = float(params.gate.post_milestone_percentile) * 100
    if metrics.deltas.size <= days:
        return None

    threshold = float(np.percentile(metrics.deltas, percentile))
    if threshold <= 0:
        return None

    recent = metrics.deltas[-days:]
    for offset, value in enumerate(reversed(recent), start=1):
        if value > threshold:
            return offset - 1, float(value)
    return None
