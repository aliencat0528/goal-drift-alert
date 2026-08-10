"""每日摘要：今天算出來但沒說的那些。

**這一塊的存在本身就是產品主張。** 沒有它，使用者無從判斷系統是安靜還是壞了——
而「懷疑它壞了」與「它真的壞了」造成的信任損失一樣大。
"""

from __future__ import annotations

from compute.forecast import Forecast
from compute.metrics import GoalMetrics
from core.config import Params
from core.models import Issue
from gate.pipeline import GateResult
from sync.quality import detector_readiness

# 被擋的理由要講人話。代碼是給程式看的，這張表是給人看的
REASON_HEADINGS = {
    "over_quota": "擠不進配額",
    "early_period": "期初",
    "post_milestone": "剛達成里程碑",
    "just_behind": "只是落後",
    "calibrating": "資料不足",
    "below_min_value": "期望損失未過門檻",
    "goal_closed": "期間已結束",
    "already_met": "已達成",
    "child_of_parent_alert": "已併入父目標",
    "observe_stage": "觀察期",
}

# 偵測器代碼同樣要講人話：使用者不需要知道哪個 min_points key 沒滿
DETECTOR_LABELS = {
    "ewma": "D5 變點",
    "monte_carlo": "達成機率",
    "historical_best": "歷史最佳 P90",
}


def render_stage(result: GateResult) -> str:
    stage = result.stage
    return (
        f"■ {result.as_of}｜{stage.label}｜系統第 {stage.day_index} 天｜"
        f"今日配額 {result.quota}｜發出 {len(result.alerts)} 則"
    )


def render_suppressed(result: GateResult) -> str:
    if not result.suppressed:
        return ""
    lines = ["■ 今日摘要：算出來但沒說的"]
    for item in result.suppressed:
        heading = REASON_HEADINGS.get(item.code, item.code)
        score = f"V={item.score:.2f}" if item.score is not None else "V=—"
        lines.append(f"  · {item.goal_name}｜{heading}｜{score}｜{item.reason}")
    return "\n".join(lines)


def render_calibration(
    metrics_by_goal: dict[str, GoalMetrics], forecasts: dict[str, Forecast], params: Params
) -> str:
    """哪些偵測器還在校準中。**不畫一條假裝可信的線**，但要說清楚還差多少。"""
    lines: list[str] = []
    for _goal_id, metrics in sorted(metrics_by_goal.items()):
        # 已結束的沒有校準的意義；還沒開始的更不必——「還差 20 天」對一個明天才起跑的目標是雜訊
        if metrics.closed or metrics.goal.start_date > metrics.as_of:
            continue
        readiness = detector_readiness(metrics.points, params)
        pending = [
            f"{DETECTOR_LABELS.get(name, name)} 還差 {info['short_by']} 天"
            for name, info in readiness.items()
            if not info["ready"]
        ]
        if pending:
            lines.append(
                f"  · {metrics.goal.name}（已有 {metrics.points} 天）：{'、'.join(pending)}"
            )

    if not lines:
        return ""
    return "\n".join(["■ 校準中（這些偵測器今天不參與判斷）", *lines])


def render_issues(issues: list[Issue]) -> str:
    if not issues:
        return ""
    rejects = [i for i in issues if i.level == "reject"]
    notes = [i for i in issues if i.level == "note"]
    lines = ["■ 資料品質"]
    for issue in rejects:
        lines.append(f"  ✗ {issue.code}｜{issue.goal_id or '-'}｜{issue.message}")
    for issue in notes:
        lines.append(f"  · {issue.code}｜{issue.goal_id or '-'}｜{issue.message}")
    return "\n".join(lines)


def render_daily(
    result: GateResult,
    metrics_by_goal: dict[str, GoalMetrics],
    forecasts: dict[str, Forecast],
    issues: list[Issue],
    params: Params,
) -> str:
    """決策卡以外的全部。狀態列不在這裡——它要排在卡片**前面**（見 `compute/report.py`）。"""
    blocks = [
        render_suppressed(result),
        render_calibration(metrics_by_goal, forecasts, params),
        render_issues(issues),
    ]
    return "\n\n".join(block for block in blocks if block)
