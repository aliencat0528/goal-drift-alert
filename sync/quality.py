"""關卡 0（契約靜態檢查）與關卡 1（資料體檢）。

這兩道關卡抓的是**統計錯誤**——機器抓得到的那一類。
語意錯誤（「已投遞」其實包含「已收藏」）與價值錯誤（統計正確但不值得打斷你）
在這裡一定抓不到，那是關卡 2 回放與人的工作（← `docs/DECISION-FLOW.md`）。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from core.config import Params
from core.models import M1_GOAL_TYPES, Dataset, Goal, Issue

# 金額型損失需要一個可乘的量。比率型目標沒有「缺口 × 單價」可算，
# 兩者湊在一起代表使用者把 schema 填錯了，而不是資料有雜訊
MONEY_LOSS_KINDS = ("linear_excess", "opportunity", "at_risk_stock")


def check_goal_contract(goals: list[Goal]) -> list[Issue]:
    """關卡 0：目標本身自相矛盾的，在算任何東西之前就擋下來。"""
    issues: list[Issue] = []
    by_id = {g.goal_id: g for g in goals}

    seen: set[str] = set()
    for goal in goals:
        if goal.goal_id in seen:
            issues.append(Issue("reject", "duplicate_goal_id", "goal_id 重複", goal.goal_id))
        seen.add(goal.goal_id)

        # 日目標的 start 與 deadline 本來就同一天，所以只擋 deadline < start
        if goal.deadline < goal.start_date:
            issues.append(
                Issue(
                    "reject",
                    "deadline_before_start",
                    f"deadline {goal.deadline} 早於 start {goal.start_date}",
                    goal.goal_id,
                )
            )
        if goal.target <= 0:
            issues.append(
                Issue("reject", "non_positive_target", f"target = {goal.target}", goal.goal_id)
            )
        if goal.type not in M1_GOAL_TYPES:
            issues.append(
                Issue(
                    "reject",
                    "unsupported_type",
                    f"M1 只實作 cumulative，本目標是 {goal.type}",
                    goal.goal_id,
                )
            )
        if goal.type == "rate" and goal.loss_kind in MONEY_LOSS_KINDS:
            issues.append(
                Issue(
                    "reject",
                    "ratio_with_money_loss",
                    f"比率型目標配了金額型損失 {goal.loss_kind}",
                    goal.goal_id,
                )
            )
        if goal.unit_value is not None and goal.loss_kind == "interrupt_only":
            issues.append(
                Issue(
                    "note",
                    "unused_unit_value",
                    "有 unit_value 但 loss_kind 是 interrupt_only，金額不會被用到",
                    goal.goal_id,
                )
            )
        if goal.parent_id and goal.parent_id not in by_id:
            issues.append(
                Issue(
                    "reject", "missing_parent", f"parent_id {goal.parent_id} 不存在", goal.goal_id
                )
            )

    issues.extend(_check_parent_cycles(by_id))
    return issues


def _check_parent_cycles(by_id: dict[str, Goal]) -> list[Issue]:
    """父子關係成環時去重會無限往上走，所以在契約層就擋掉。"""
    issues: list[Issue] = []
    for goal_id in by_id:
        seen = {goal_id}
        cursor = by_id[goal_id].parent_id
        while cursor and cursor in by_id:
            if cursor in seen:
                issues.append(Issue("reject", "parent_cycle", "parent_id 形成環", goal_id))
                break
            seen.add(cursor)
            cursor = by_id[cursor].parent_id
    return issues


def check_data_health(dataset: Dataset, params: Params, as_of: date) -> list[Issue]:
    """關卡 1：資料量夠不夠、有沒有斷天、有沒有明顯不合理的累積量。"""
    issues: list[Issue] = []
    by_goal: dict[str, list] = defaultdict(list)
    for entry in dataset.progress:
        by_goal[entry.goal_id].append(entry)

    overshoot = params.gate.overshoot_ratio
    for goal in dataset.goals:
        entries = by_goal.get(goal.goal_id, [])
        # 「期間外」比對的是目標的 start–deadline，不是 as_of。
        # 晚於 as_of 的列不是資料問題，那是回放：回放時未來的資料本來就存在，只是還不該被看到
        in_window = [e for e in entries if goal.start_date <= e.date <= goal.deadline]
        outside = len(entries) - len(in_window)
        if outside:
            issues.append(
                Issue(
                    "note",
                    "progress_outside_window",
                    f"{outside} 筆進度落在目標期間外，不計入累積",
                    goal.goal_id,
                )
            )

        counted = [e for e in in_window if e.date <= as_of]
        cumulative = sum(e.delta for e in counted)
        if cumulative > goal.target * overshoot:
            issues.append(
                Issue(
                    "note",
                    "target_too_low",
                    f"累積 {cumulative:g} 已達 target 的 "
                    f"{cumulative / goal.target:.0%}，目標可能訂太低",
                    goal.goal_id,
                )
            )
        # 只對**進行中**的目標報「沒有進度列」：已結束的目標沒有列是結果，不是資料問題
        if not counted and goal.start_date <= as_of <= goal.deadline:
            issues.append(Issue("note", "no_progress_rows", "期間內沒有任何進度列", goal.goal_id))

        gap_sources = {e.source for e in counted if e.source == "notion_diff_gap"}
        if gap_sources:
            issues.append(
                Issue(
                    "note",
                    "diff_gap",
                    "含 notion_diff_gap 的列：run rate 可能出現假峰值",
                    goal.goal_id,
                )
            )
    return issues


def detector_readiness(points: int, params: Params) -> dict[str, dict]:
    """各偵測器的資料量夠不夠。不夠的**停用並標「校準中」**，不是照跑然後畫一條假裝可信的線。"""
    min_points = params.cold_start.min_points
    readiness = {}
    # 只列**已上線**的偵測器所需的量。`seasonal`（D1）與 `survival_events`（D6）排 M2，
    # 報「季節分解還差 12 天」只會讓人以為那個偵測器隨時會啟用（← prepare.md AG-008）
    for name in ("ewma", "monte_carlo", "historical_best"):
        needed = min_points[name]
        readiness[name] = {
            "ready": points >= needed,
            "points": points,
            "needed": needed,
            "short_by": max(needed - points, 0),
        }
    return readiness


def summarize(issues: list[Issue]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for issue in issues:
        counts[issue.level] += 1
    return dict(counts)


def rejected_goal_ids(issues: list[Issue]) -> set[str]:
    """被關卡 0 擋下的目標。這些目標不進 compute——算了也只是把錯誤帶到下游。"""
    return {i.goal_id for i in issues if i.level == "reject" and i.goal_id}
