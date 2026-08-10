"""CSV 載入。

用 stdlib `csv` 而非 pandas：這一層每一列都要回報「錯在哪一列、為什麼」，
而逐列帶訊息的驗證在 DataFrame 裡反而繞。pandas 留給真的需要向量運算的地方
（`sync/snapshot.py` 的差分、`compute/` 的滾動視窗）。
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from core.models import (
    LOSS_KINDS,
    PROGRESS_SOURCES,
    Dataset,
    Goal,
    Issue,
    ProgressEntry,
)

GOALS_FILE = "goals.csv"
PROGRESS_FILE = "progress.csv"


def _parse_date(raw: str, field: str, where: str, issues: list[Issue]) -> date | None:
    try:
        return date.fromisoformat(raw.strip())
    except (ValueError, AttributeError):
        issues.append(Issue("reject", "bad_date", f"{where}：{field} 不是 ISO 日期（{raw!r}）"))
        return None


def _parse_number(raw: str, field: str, where: str, issues: list[Issue]) -> float | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        issues.append(Issue("reject", "bad_number", f"{where}：{field} 不是數字（{raw!r}）"))
        return None


def load_goals(path: Path) -> tuple[list[Goal], list[Issue]]:
    """讀 `goals.csv`。回傳（成功解析的目標, 問題清單）。"""
    goals: list[Goal] = []
    issues: list[Issue] = []
    if not path.exists():
        issues.append(Issue("reject", "missing_file", f"找不到目標檔：{path}"))
        return goals, issues

    with open(path, encoding="utf-8", newline="") as fh:
        for lineno, row in enumerate(csv.DictReader(fh), start=2):
            goal_id = (row.get("goal_id") or "").strip()
            where = f"{path.name}:{lineno}"
            if not goal_id:
                issues.append(Issue("reject", "missing_goal_id", f"{where}：goal_id 空白"))
                continue

            start = _parse_date(row.get("start_date", ""), "start_date", where, issues)
            deadline = _parse_date(row.get("deadline", ""), "deadline", where, issues)
            target = _parse_number(row.get("target", ""), "target", where, issues)
            if start is None or deadline is None or target is None:
                continue

            loss_kind = (row.get("loss_kind") or "").strip() or "interrupt_only"
            if loss_kind not in LOSS_KINDS:
                issues.append(
                    Issue(
                        "reject",
                        "bad_loss_kind",
                        f"{where}：loss_kind 不在型錄內（{loss_kind}）",
                        goal_id,
                    )
                )
                continue

            goals.append(
                Goal(
                    goal_id=goal_id,
                    name=(row.get("name") or goal_id).strip(),
                    type=(row.get("type") or "cumulative").strip(),
                    target=target,
                    start_date=start,
                    deadline=deadline,
                    unit_value=_parse_number(
                        row.get("unit_value", ""), "unit_value", where, issues
                    ),
                    loss_kind=loss_kind,
                    parent_id=(row.get("parent_id") or "").strip() or None,
                    owner=(row.get("owner") or "self").strip(),
                )
            )
    return goals, issues


def load_progress(path: Path, known_goal_ids: set[str]) -> tuple[list[ProgressEntry], list[Issue]]:
    """讀 `progress.csv`。

    兩條在這裡就擋掉的規則（← `docs/DATA-CONTRACT.md` 資料品質檢查）：
    `goal_id` 不存在 → 拒絕寫入；`delta` 為負 → 視為 Notion 端的修正，記錄但不寫入。
    """
    entries: list[ProgressEntry] = []
    issues: list[Issue] = []
    if not path.exists():
        issues.append(Issue("reject", "missing_file", f"找不到進度檔：{path}"))
        return entries, issues

    with open(path, encoding="utf-8", newline="") as fh:
        for lineno, row in enumerate(csv.DictReader(fh), start=2):
            where = f"{path.name}:{lineno}"
            goal_id = (row.get("goal_id") or "").strip()
            entry_date = _parse_date(row.get("date", ""), "date", where, issues)
            delta = _parse_number(row.get("delta", ""), "delta", where, issues)
            if entry_date is None or delta is None:
                continue
            if goal_id not in known_goal_ids:
                issues.append(
                    Issue(
                        "reject", "unknown_goal_id", f"{where}：goal_id 不在 goals.csv 內", goal_id
                    )
                )
                continue
            if delta < 0:
                issues.append(
                    Issue(
                        "note",
                        "negative_delta",
                        f"{where}：delta 為負（{delta}），視為修正不寫入",
                        goal_id,
                    )
                )
                continue

            source = (row.get("source") or "manual").strip()
            if source not in PROGRESS_SOURCES:
                issues.append(
                    Issue(
                        "note", "unknown_source", f"{where}：source 不在型錄內（{source}）", goal_id
                    )
                )
            entries.append(
                ProgressEntry(date=entry_date, goal_id=goal_id, delta=delta, source=source)
            )
    return entries, issues


def load_dataset(data_dir: Path) -> Dataset:
    """讀一整個資料目錄。檢查（關卡 0／1）由 `sync.quality` 另外跑，這裡只負責讀。"""
    goals, goal_issues = load_goals(data_dir / GOALS_FILE)
    progress, progress_issues = load_progress(data_dir / PROGRESS_FILE, {g.goal_id for g in goals})
    return Dataset(goals=goals, progress=progress, issues=goal_issues + progress_issues)
