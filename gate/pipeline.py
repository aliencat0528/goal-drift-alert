"""決策閘主流程：評分 → 去重 → 排擠 → 取前 N。

**配額是硬上限，不是建議值。** 擠不進去的沉進每日摘要，不因為「這則很重要」而破例——
會破例的配額不是配額，而沒有配額就沒有「注意力是預算」這件事。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from compute.detect import Candidate
from compute.forecast import Forecast
from compute.metrics import GoalMetrics
from core.config import Params
from core.models import Goal
from gate.rules import STAGE_OBSERVE, Stage, resolve_stage, suppression_reason
from gate.value import ValueBreakdown, compute_value

KIND_ALERT = "alert"
KIND_RETARGET = "retarget"


@dataclass
class Alert:
    """通過決策閘的一則。`kind=retarget` 是「建議改目標」——它不叫你更努力。"""

    candidate: Candidate
    metrics: GoalMetrics
    forecast: Forecast
    breakdown: ValueBreakdown
    kind: str = KIND_ALERT
    merged: list[Candidate] = field(default_factory=list)
    extra_evidence: list[str] = field(default_factory=list)

    @property
    def goal(self) -> Goal:
        return self.metrics.goal

    @property
    def score(self) -> float:
        """排序用。可救性歸零時 V 必為負，改用賭注大小排——它仍然要競爭同一份配額。"""
        return self.breakdown.stake if self.kind == KIND_RETARGET else self.breakdown.value

    def all_evidence(self) -> list[str]:
        lines = list(self.candidate.evidence)
        for candidate in self.merged:
            lines.append(f"同時觸發｜{candidate.label}：{candidate.headline}")
            lines.extend(f"　{line}" for line in candidate.evidence)
        lines.extend(self.extra_evidence)
        return lines


@dataclass
class Suppressed:
    """被擋下來的一則。**擋掉的必須被看見**——否則使用者只會覺得系統很安靜，然後懷疑它壞了。"""

    goal_id: str
    goal_name: str
    trigger: str
    code: str
    reason: str
    score: float | None = None


@dataclass
class GateResult:
    stage: Stage
    quota: int
    as_of: date
    alerts: list[Alert] = field(default_factory=list)
    suppressed: list[Suppressed] = field(default_factory=list)


def _ancestors(goal: Goal, goals: dict[str, Goal]) -> list[str]:
    chain: list[str] = []
    cursor = goal.parent_id
    seen = {goal.goal_id}
    while cursor and cursor in goals and cursor not in seen:
        chain.append(cursor)
        seen.add(cursor)
        cursor = goals[cursor].parent_id
    return chain


def _score_candidates(
    candidates: list[Candidate],
    metrics_by_goal: dict[str, GoalMetrics],
    forecasts: dict[str, Forecast],
    params: Params,
) -> tuple[list[Alert], list[Suppressed]]:
    scored: list[Alert] = []
    suppressed: list[Suppressed] = []
    min_value = float(params.gate.min_value)

    for candidate in candidates:
        metrics = metrics_by_goal[candidate.goal_id]
        forecast = forecasts[candidate.goal_id]
        name = metrics.goal.name

        reason = suppression_reason(candidate, metrics, params)
        if reason:
            code, text = reason
            suppressed.append(Suppressed(candidate.goal_id, name, candidate.trigger, code, text))
            continue

        breakdown = compute_value(metrics, forecast, params, candidate.p_risk)
        if breakdown.salvageability <= 0:
            scored.append(Alert(candidate, metrics, forecast, breakdown, kind=KIND_RETARGET))
            continue
        if breakdown.value <= min_value:
            suppressed.append(
                Suppressed(
                    candidate.goal_id,
                    name,
                    candidate.trigger,
                    "below_min_value",
                    f"V = {breakdown.value:.2f} 未超過門檻 {min_value:.2f}",
                    breakdown.value,
                )
            )
            continue
        scored.append(Alert(candidate, metrics, forecast, breakdown))
    return scored, suppressed


def _dedup_same_goal(alerts: list[Alert]) -> list[Alert]:
    """同一個 goal_id 的多個觸發合併成一則：取 V 最高者當標題，其餘列為證據。"""
    by_goal: dict[str, list[Alert]] = {}
    for alert in alerts:
        by_goal.setdefault(alert.goal.goal_id, []).append(alert)

    merged: list[Alert] = []
    for group in by_goal.values():
        group.sort(key=lambda a: (-a.score, a.candidate.severity_rank))
        head, rest = group[0], group[1:]
        head.merged.extend(item.candidate for item in rest)
        merged.append(head)
    return merged


def _dedup_parent_child(
    alerts: list[Alert], goals: dict[str, Goal]
) -> tuple[list[Alert], list[Suppressed]]:
    """父子目標同時觸發時只發父目標——否則月／週／日會為同一件事發三次。"""
    alert_ids = {alert.goal.goal_id for alert in alerts}
    kept: list[Alert] = []
    suppressed: list[Suppressed] = []
    by_id = {alert.goal.goal_id: alert for alert in alerts}

    for alert in alerts:
        ancestors = [gid for gid in _ancestors(alert.goal, goals) if gid in alert_ids]
        if not ancestors:
            kept.append(alert)
            continue
        parent = by_id[ancestors[0]]
        parent.extra_evidence.append(f"子目標｜{alert.goal.name}：{alert.candidate.headline}")
        suppressed.append(
            Suppressed(
                alert.goal.goal_id,
                alert.goal.name,
                alert.candidate.trigger,
                "child_of_parent_alert",
                f"父目標「{parent.goal.name}」已發，本則併入其證據",
                alert.score,
            )
        )
    return kept, suppressed


def run_gate(
    candidates: list[Candidate],
    metrics_by_goal: dict[str, GoalMetrics],
    forecasts: dict[str, Forecast],
    goals: dict[str, Goal],
    params: Params,
    as_of: date,
    system_start: date | None,
) -> GateResult:
    """把候選警示變成「今天要說的話」與「今天沒說但你看得到的話」。"""
    stage = resolve_stage(system_start, as_of, params)
    scored, suppressed = _score_candidates(candidates, metrics_by_goal, forecasts, params)

    scored = _dedup_same_goal(scored)
    scored, child_suppressed = _dedup_parent_child(scored, goals)
    suppressed.extend(child_suppressed)

    scored.sort(key=lambda a: (-a.score, a.candidate.severity_rank, a.goal.goal_id))

    if stage.name == STAGE_OBSERVE:
        for alert in scored:
            suppressed.append(
                Suppressed(
                    alert.goal.goal_id,
                    alert.goal.name,
                    alert.candidate.trigger,
                    "observe_stage",
                    f"觀察期第 {stage.day_index} 天，只收不發",
                    alert.score,
                )
            )
        return GateResult(stage=stage, quota=0, as_of=as_of, alerts=[], suppressed=suppressed)

    quota = stage.quota
    passed = scored[:quota]
    for rank, alert in enumerate(scored[quota:], start=quota + 1):
        suppressed.append(
            Suppressed(
                alert.goal.goal_id,
                alert.goal.name,
                alert.candidate.trigger,
                "over_quota",
                f"排在第 {rank} 位，今日配額 {quota}",
                alert.score,
            )
        )

    suppressed.sort(key=lambda s: (s.score is None, -(s.score or 0.0)))
    return GateResult(stage=stage, quota=quota, as_of=as_of, alerts=passed, suppressed=suppressed)
