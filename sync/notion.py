"""Notion 接入：把「職缺搜集情況」拉成一份每日快照。

**本模組不在 `compute.report` 的路徑上**，要跑得手動執行（或掛 cron）：

    NOTION_TOKEN=secret_xxx python3 -m sync.notion --data-dir data

分開跑是刻意的——報表要能在沒有網路、沒有 token 的情況下用既有快照跑完。
把網路呼叫放進報表路徑，等於讓「Notion 掛了」變成「今天沒有風險判斷」。

兩條資料路徑（← `docs/DATA-CONTRACT.md` 已知缺口與補法）：

- **狀態計數 → 快照差分**：現有資料立刻可用，精度受限於一天一次
- **createdTime → 收集日**：createdTime 是系統自動寫的，是唯一可靠的時間戳
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from core.config import load_params
from core.models import ProgressEntry, SnapshotRow, business_date
from sync.snapshot import write_snapshot

# 快照要存哪些維度。多存幾個維度成本是零（都在同一次查詢裡），
# 少存則要等下一天才補得回來——快照補不了過去
SNAPSHOT_DIMENSIONS = ("狀態", "公司", "求職管道")


def parse_data_source_id(raw: str) -> str:
    """`collection://<uuid>` → `<uuid>`。設定檔存完整 URI 是為了讓人一眼看出它指向哪。"""
    return raw.split("://", 1)[1] if "://" in raw else raw


def property_value(prop: dict) -> str | None:
    """取單一屬性的顯示值。只處理快照會用到的型別，其餘回 None。"""
    kind = prop.get("type")
    if kind in ("select", "status"):
        node = prop.get(kind)
        return node.get("name") if node else None
    if kind == "multi_select":
        names = [item["name"] for item in prop.get("multi_select", [])]
        return "／".join(names) if names else None
    if kind == "created_time":
        return prop.get("created_time")
    if kind == "date":
        node = prop.get("date")
        return node.get("start") if node else None
    if kind == "title":
        parts = [item.get("plain_text", "") for item in prop.get("title", [])]
        return "".join(parts) or None
    return None


def fetch_pages(client, data_source_id: str) -> list[dict]:
    """把整個資料庫翻完。個人規模的資料量（百列等級）不需要增量查詢。"""
    pages: list[dict] = []
    cursor = None
    while True:
        payload = {"database_id": data_source_id, "page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        response = client.databases.query(**payload)
        pages.extend(response.get("results", []))
        if not response.get("has_more"):
            break
        cursor = response.get("next_cursor")
    return pages


def build_snapshot(
    pages: list[dict], data_source: str, snapshot_date: date, dimensions=SNAPSHOT_DIMENSIONS
) -> list[SnapshotRow]:
    """把頁面清單壓成 (維度, 值, 筆數) 三元組。"""
    counters: dict[str, Counter] = {dim: Counter() for dim in dimensions}
    for page in pages:
        props = page.get("properties", {})
        for dim in dimensions:
            prop = props.get(dim)
            if not prop:
                continue
            value = property_value(prop)
            if value:
                counters[dim][value] += 1

    rows: list[SnapshotRow] = []
    for dim, counter in counters.items():
        for value, count in sorted(counter.items()):
            rows.append(
                SnapshotRow(
                    snapshot_date=snapshot_date,
                    data_source=data_source,
                    dimension=dim,
                    value=value,
                    count=count,
                )
            )
    return rows


def created_time_progress(
    pages: list[dict], goal_id: str, boundary_hour: int
) -> list[ProgressEntry]:
    """用 createdTime 還原「每天收集了幾筆」。

    這條路徑不需要差分，因為 createdTime 本身就是事件時間戳——
    這也是為什麼收集量比投遞量可信：投遞只有狀態，狀態沒有時間。
    """
    counter: Counter = Counter()
    for page in pages:
        created = page.get("created_time")
        if not created:
            continue
        moment = datetime.fromisoformat(created.replace("Z", "+00:00"))
        counter[business_date(moment, boundary_hour)] += 1

    return [
        ProgressEntry(date=day, goal_id=goal_id, delta=float(count), source="notion_diff")
        for day, count in sorted(counter.items())
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="拉一次 Notion 快照並寫入 data/snapshots/")
    parser.add_argument("--data-dir", default="data", help="資料目錄（預設 data）")
    parser.add_argument("--config", default=None, help="參數檔路徑")
    parser.add_argument("--date", default=None, help="快照日期，預設今天")
    args = parser.parse_args(argv)

    token = os.environ.get("NOTION_TOKEN")
    if not token:
        print("缺少 NOTION_TOKEN 環境變數。憑證不進版控，也不寫進 params.yaml。", file=sys.stderr)
        return 2

    try:
        from notion_client import Client
    except ImportError:
        print("未安裝 notion-client：pip install -r requirements.txt", file=sys.stderr)
        return 2

    params = load_params(args.config)
    data_source_uri = params.sync.notion.jobs_data_source
    data_source_id = parse_data_source_id(data_source_uri)
    snapshot_date = date.fromisoformat(args.date) if args.date else date.today()

    client = Client(auth=token)
    pages = fetch_pages(client, data_source_id)
    rows = build_snapshot(pages, data_source_uri, snapshot_date)
    if not rows:
        print(
            "查詢結果是空的，不寫快照（寫一份全零的快照會讓明天的差分出現假峰值）", file=sys.stderr
        )
        return 1

    path = write_snapshot(rows, Path(args.data_dir) / "snapshots")
    print(f"已寫入 {path}（{len(pages)} 筆頁面、{len(rows)} 組維度值）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
