"""每日執行入口：讀資料 → 算指標 → 偵測 → 決策閘 → 決策卡。

    python3 -m compute.report --data-dir data/examples --as-of 2026-08-30

放在 `compute` 底下是因為 README 的快速開始就是這個指令；它自己只做編排，
每一步的邏輯都在對應模組裡。**這裡不出現任何門檻值**。
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from compute.detect import detect_all
from compute.metrics import compute_all
from core.config import load_params
from dash.card import render_cards
from dash.summary import render_daily, render_stage
from gate.pipeline import run_gate
from sync.loader import GOALS_FILE, load_dataset
from sync.quality import check_data_health, check_goal_contract, rejected_goal_ids
from sync.snapshot import diff_to_progress, load_snapshots, merge_progress

DEFAULT_OUT = Path("out/decision-cards.md")


def _system_start(dataset, as_of: date) -> date | None:
    """系統上線日＝最早的那一筆資料。冷啟動的分級是從這天開始數的。"""
    days = [entry.date for entry in dataset.progress]
    days.extend(goal.start_date for goal in dataset.goals if goal.start_date <= as_of)
    return min(days) if days else None


def build_report(data_dir: Path, params, as_of: date, explain: bool) -> tuple[str, int]:
    """回傳（報告全文, 發出的決策卡數）。"""
    dataset = load_dataset(data_dir)
    if not dataset.goals:
        raise SystemExit(
            f"{data_dir / GOALS_FILE} 讀不到任何目標。"
            f"先 cp data/examples/goals.csv {data_dir}/goals.csv 起步。"
        )

    # 快照差分還原的流量與人工補登並行，同一天兩邊都有值時以補登為準
    snapshots = load_snapshots(data_dir / "snapshots")
    diff_entries, diff_issues = diff_to_progress(snapshots, params)
    dataset.progress, merge_issues = merge_progress(dataset.progress, diff_entries)
    dataset.issues.extend(diff_issues + merge_issues)

    dataset.issues.extend(check_goal_contract(dataset.goals))
    skip = rejected_goal_ids(dataset.issues)
    dataset.issues.extend(check_data_health(dataset, params, as_of))

    metrics_by_goal = compute_all(dataset, params, as_of, skip_ids=skip)
    candidates, forecasts = detect_all(metrics_by_goal, params)
    result = run_gate(
        candidates=candidates,
        metrics_by_goal=metrics_by_goal,
        forecasts=forecasts,
        goals={g.goal_id: g for g in dataset.goals},
        params=params,
        as_of=as_of,
        system_start=_system_start(dataset, as_of),
    )

    # 狀態列排在最前面：卡片要在什麼前提下讀（影子模式？分級發布？），必須先講
    blocks = [render_stage(result)]
    if result.alerts:
        blocks.append(render_cards(result.alerts, params, explain=explain))
    blocks.append(render_daily(result, metrics_by_goal, forecasts, dataset.issues, params))
    return "\n\n".join(block for block in blocks if block), len(result.alerts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="產生今日決策卡與每日摘要")
    parser.add_argument("--data-dir", default="data", help="資料目錄（預設 data）")
    parser.add_argument("--config", default=None, help="參數檔路徑，預設 config/params.yaml")
    parser.add_argument(
        "--as-of", default=None, help="以哪一天為準（ISO 日期），預設今天。回放用這個"
    )
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="輸出檔路徑")
    parser.add_argument("--explain", action="store_true", help="附上 V 的完整推導")
    parser.add_argument("--no-write", action="store_true", help="只印到終端機，不寫檔")
    args = parser.parse_args(argv)

    params = load_params(args.config)
    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
    report, alert_count = build_report(Path(args.data_dir), params, as_of, args.explain)

    print(report)
    if not args.no_write:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report + "\n", encoding="utf-8")
        print(f"\n（已寫入 {out_path}）", file=sys.stderr)
    return 0 if alert_count >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
