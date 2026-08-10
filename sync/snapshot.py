"""每日快照與差分還原流量。

**Notion 的 status 變更沒有時間戳**：存量拿得到（現在有幾筆已投遞），
流量拿不到（今天投了幾筆）——而目標偏移要的正是流量。
所以每天 23:00 存一次各狀態的計數，用 `delta(t) = count(t) − count(t-1)` 還原。

代價寫在 `notion_diff_gap` 這個 source 上：漏跑一天，第一筆差分會把兩天的量記在同一天。
不標出來的話 run rate 會出現一個假峰值，而假峰值會把歷史最佳 P90 墊高，
接著可行性翻轉就永遠不會觸發——**一個資料品質問題會靜悄悄地關掉整個偵測器**。
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

import pandas as pd

from core.config import Params
from core.models import Issue, ProgressEntry, SnapshotRow

SNAPSHOT_COLUMNS = ("snapshot_date", "data_source", "dimension", "value", "count")


def snapshot_path(snapshot_dir: Path, day: date) -> Path:
    return snapshot_dir / f"{day.isoformat()}.csv"


def write_snapshot(rows: list[SnapshotRow], snapshot_dir: Path) -> Path:
    """寫入單日快照。同一天重跑會覆蓋——快照是狀態，不是事件，重跑不該累加。"""
    if not rows:
        raise ValueError("沒有可寫入的快照列")
    days = {row.snapshot_date for row in rows}
    if len(days) != 1:
        raise ValueError(f"一次只能寫一天的快照，收到 {sorted(days)}")

    snapshot_dir.mkdir(parents=True, exist_ok=True)
    path = snapshot_path(snapshot_dir, days.pop())
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(SNAPSHOT_COLUMNS)
        for row in rows:
            writer.writerow(
                [
                    row.snapshot_date.isoformat(),
                    row.data_source,
                    row.dimension,
                    row.value,
                    row.count,
                ]
            )
    return path


def load_snapshots(snapshot_dir: Path) -> pd.DataFrame:
    """讀進整個快照目錄。沒有目錄或沒有檔案時回傳空表，不是錯誤（首次執行就是這樣）。"""
    empty = pd.DataFrame(columns=list(SNAPSHOT_COLUMNS))
    if not snapshot_dir.exists():
        return empty
    files = sorted(snapshot_dir.glob("*.csv"))
    if not files:
        return empty

    frames = [pd.read_csv(f) for f in files]
    df = pd.concat(frames, ignore_index=True)
    df["snapshot_date"] = pd.to_datetime(df["snapshot_date"]).dt.date
    df["count"] = pd.to_numeric(df["count"], errors="coerce").fillna(0).astype(int)
    return df.sort_values(["data_source", "dimension", "value", "snapshot_date"], ignore_index=True)


def _progress_map(params: Params) -> dict[tuple[str, str], str]:
    """(維度, 值) → goal_id。對應是設定不是推論——猜錯會變成語意錯誤，機器抓不到。"""
    mapping: dict[tuple[str, str], str] = {}
    for item in params.sync.notion.get("progress_map", []):
        mapping[(item["dimension"], item["value"])] = item["goal_id"]
    return mapping


def diff_to_progress(df: pd.DataFrame, params: Params) -> tuple[list[ProgressEntry], list[Issue]]:
    """把快照序列差分成 progress 增量。"""
    entries: list[ProgressEntry] = []
    issues: list[Issue] = []
    if df.empty:
        return entries, issues

    mapping = _progress_map(params)
    if not mapping:
        issues.append(
            Issue(
                "note", "no_progress_map", "sync.notion.progress_map 是空的，快照不會產生任何進度"
            )
        )
        return entries, issues

    for (dimension, value), group in df.groupby(["dimension", "value"], sort=True):
        goal_id = mapping.get((dimension, value))
        if goal_id is None:
            continue

        group = group.sort_values("snapshot_date")
        previous_date = None
        previous_count = None
        for row in group.itertuples(index=False):
            current_date = row.snapshot_date
            current_count = int(row.count)
            if previous_count is None:
                # 第一筆沒有基準可差分。它是存量不是流量，寫進 progress 會變成一個假的巨大增量
                issues.append(
                    Issue(
                        "note",
                        "snapshot_baseline",
                        f"{current_date} {dimension}/{value} 為基準快照"
                        f"（存量 {current_count}），不產生增量",
                        goal_id,
                    )
                )
                previous_date, previous_count = current_date, current_count
                continue

            delta = current_count - previous_count
            gap_days = (current_date - previous_date).days
            if delta < 0:
                issues.append(
                    Issue(
                        "note",
                        "negative_diff",
                        f"{current_date} {dimension}/{value} 差分為負（{delta}），"
                        f"視為 Notion 端修正，不寫入",
                        goal_id,
                    )
                )
            elif delta > 0:
                source = "notion_diff" if gap_days == 1 else "notion_diff_gap"
                if source == "notion_diff_gap":
                    issues.append(
                        Issue(
                            "note",
                            "snapshot_gap",
                            f"{current_date} 距上次快照 {gap_days} 天，{delta:g} 筆被記在同一天",
                            goal_id,
                        )
                    )
                entries.append(
                    ProgressEntry(
                        date=current_date, goal_id=goal_id, delta=float(delta), source=source
                    )
                )
            previous_date, previous_count = current_date, current_count

    entries.sort(key=lambda e: (e.date, e.goal_id))
    return entries, issues


def merge_progress(
    csv_entries: list[ProgressEntry], diff_entries: list[ProgressEntry]
) -> tuple[list[ProgressEntry], list[Issue]]:
    """CSV 補登與快照差分並行時的合併。

    同一天同一目標兩邊都有值時**以人工補登為準**（← `docs/DATA-CONTRACT.md` 補法 a + c），
    差異記成資料品質指標。差異本身是有用的訊號：它在說快照的精度掉了多少。
    """
    issues: list[Issue] = []
    by_key = {(e.date, e.goal_id): e for e in diff_entries}
    for entry in csv_entries:
        key = (entry.date, entry.goal_id)
        if key in by_key and by_key[key].delta != entry.delta:
            issues.append(
                Issue(
                    "note",
                    "source_disagreement",
                    f"{entry.date} 補登 {entry.delta:g} vs "
                    f"快照差分 {by_key[key].delta:g}，以補登為準",
                    entry.goal_id,
                )
            )
        by_key[key] = entry

    merged = sorted(by_key.values(), key=lambda e: (e.date, e.goal_id))
    return merged, issues
