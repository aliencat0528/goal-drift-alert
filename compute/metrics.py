"""目標偏移指標。

一句話版本：`pace ratio` 說你落後多少，`required rate` 說你接下來要多快，
`歷史最佳 P90` 說你最快能多快——**只有第三個數字能把「落後」翻譯成「不可能」**，
而那正是這個系統唯一真正需要說話的時刻。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from core.config import Params
from core.models import Dataset, Goal, ProgressEntry


@dataclass
class GoalMetrics:
    """單一目標在某一天的全部指標。決策卡上的每個數字都要能追回這裡。"""

    goal: Goal
    as_of: date
    dates: list[date]
    deltas: np.ndarray

    total_days: int
    elapsed_days: int
    remaining_days: int
    elapsed_ratio: float
    remaining_time_ratio: float
    closed: bool

    cumulative: float
    gap: float
    attainment: float
    pace_ratio: float | None
    spi: float | None
    cpi: float | None

    run_rate: float
    required_rate: float | None
    pressure: float | None
    hist_best_rate: float | None
    hist_best_basis: str | None
    buffer_consumption: float | None

    silence_days: int
    silence_threshold: float | None
    points: int

    @property
    def on_track(self) -> bool:
        return self.gap <= 0

    def sustained_days_needed(self) -> int | None:
        """維持歷史最佳也要連續幾天。決策卡的「維持原目標」選項要用這個數字說話。"""
        if not self.hist_best_rate or self.hist_best_rate <= 0 or self.gap <= 0:
            return None
        return math.ceil(self.gap / self.hist_best_rate)


def build_daily_series(
    goal: Goal, entries: list[ProgressEntry], as_of: date
) -> tuple[list[date], np.ndarray]:
    """把稀疏的 progress 列攤成連續日序列（沒有進展的日子補 0）。

    補 0 不是實作細節，是語意：**沒寫的那天是「做了 0 件」，不是「沒有資料」**。
    當成缺值會讓 run rate 只由有動作的日子構成，於是永遠看起來很健康。
    """
    end = min(as_of, goal.deadline)
    if end < goal.start_date:
        return [], np.array([], dtype=float)

    span = (end - goal.start_date).days + 1
    days = [goal.start_date + timedelta(days=i) for i in range(span)]
    index = {day: i for i, day in enumerate(days)}
    deltas = np.zeros(span, dtype=float)
    for entry in entries:
        position = index.get(entry.date)
        if position is not None:
            deltas[position] += entry.delta
    return days, deltas


def rolling_mean(values: np.ndarray, window: int) -> np.ndarray:
    """完整視窗的滾動平均。視窗不足時回空陣列——不足的視窗只會製造假的低點。"""
    if window <= 0 or values.size < window:
        return np.array([], dtype=float)
    kernel = np.ones(window, dtype=float) / window
    return np.convolve(values, kernel, mode="valid")


def historical_best_rate(deltas: np.ndarray, params: Params) -> tuple[float | None, str | None]:
    """歷史最佳 run rate（P90）。

    取的是**持續速率**而不是單日最高：連續 7 日平均的 P90。
    用單日最高當「你做得到的速度」會高估——一天投 8 份不代表你能連著兩週每天 8 份，
    而 required rate 問的正是「接下來每天」。
    """
    window = int(params.detector.best_rate_window_days)
    percentile = float(params.drift.feasibility_percentile) * 100
    minimum = int(params.cold_start.min_points.historical_best)

    if deltas.size < minimum:
        return None, None
    sustained = rolling_mean(deltas, window)
    if sustained.size == 0:
        return None, None
    return float(np.percentile(sustained, percentile)), f"連續 {window} 日平均的 P{percentile:.0f}"


def silence_stats(
    dates: list[date], deltas: np.ndarray, as_of: date, params: Params
) -> tuple[int, float | None]:
    """靜默天數，以及「多久算異常」的門檻（歷史間隔的 P85）。

    門檻由資料決定而非由人定：每天投遞的人靜默 3 天是異常，每週投一次的人靜默 3 天很正常。
    """
    if deltas.size == 0:
        return 0, None

    active = [day for day, value in zip(dates, deltas, strict=True) if value > 0]
    silence_days = (as_of - active[-1]).days if active else len(dates)

    if len(active) < 3:
        return silence_days, None
    gaps = [(later - earlier).days for earlier, later in zip(active, active[1:], strict=False)]
    threshold = float(np.percentile(gaps, float(params.drift.silence_percentile) * 100))
    return silence_days, threshold


def compute_goal(
    goal: Goal, entries: list[ProgressEntry], params: Params, as_of: date
) -> GoalMetrics:
    """算完一個目標的所有指標。這裡不做任何「是否異常」的判斷。"""
    dates, deltas = build_daily_series(goal, entries, as_of)
    cumulative = float(deltas.sum())
    gap = max(goal.target - cumulative, 0.0)

    elapsed_days = goal.elapsed_days(as_of)
    remaining_days = goal.remaining_days(as_of)
    elapsed_ratio = goal.elapsed_ratio(as_of)
    attainment = cumulative / goal.target if goal.target else 0.0

    # SPI 在線性計畫下與 pace ratio 同值（EV/PV 的 PV 就是 target × 時間消耗比）。
    # 兩個都留是為了讓決策卡講得出 EVM 的語言，不是因為它們是兩個獨立訊號
    pace_ratio = attainment / elapsed_ratio if elapsed_ratio > 0 else None
    spi = pace_ratio

    window = int(params.drift.run_rate_window_days)
    recent = deltas[-window:] if deltas.size else deltas
    run_rate = float(recent.mean()) if recent.size else 0.0

    required_rate = gap / remaining_days if remaining_days > 0 else None
    if required_rate is None:
        pressure = None
    elif run_rate > 0:
        pressure = required_rate / run_rate
    else:
        pressure = math.inf if required_rate > 0 else 0.0

    hist_best, hist_basis = historical_best_rate(deltas, params)
    buffer_consumption = None
    if hist_best and hist_best > 0 and required_rate is not None:
        buffer_consumption = min(required_rate / hist_best, 1.0)

    silence_days, silence_threshold = silence_stats(dates, deltas, as_of, params)

    return GoalMetrics(
        goal=goal,
        as_of=as_of,
        dates=dates,
        deltas=deltas,
        total_days=goal.total_days,
        elapsed_days=elapsed_days,
        remaining_days=remaining_days,
        elapsed_ratio=elapsed_ratio,
        remaining_time_ratio=goal.remaining_time_ratio(as_of),
        closed=goal.is_closed(as_of),
        cumulative=cumulative,
        gap=gap,
        attainment=attainment,
        pace_ratio=pace_ratio,
        spi=spi,
        # CPI 需要「投入」才算得出來，而投入在 week task tracker 裡是純文字時間區段，
        # 要 parser 才轉得成時數（← docs/DATA-CONTRACT.md），排 M2
        cpi=None,
        run_rate=run_rate,
        required_rate=required_rate,
        pressure=pressure,
        hist_best_rate=hist_best,
        hist_best_basis=hist_basis,
        buffer_consumption=buffer_consumption,
        silence_days=silence_days,
        silence_threshold=silence_threshold,
        points=int(deltas.size),
    )


def compute_all(
    dataset: Dataset, params: Params, as_of: date, skip_ids: set[str] | None = None
) -> dict[str, GoalMetrics]:
    """算全部目標。被關卡 0 擋下的（`skip_ids`）不算——算了只是把錯誤帶到下游。"""
    skip = skip_ids or set()
    by_goal: dict[str, list[ProgressEntry]] = {}
    for entry in dataset.progress:
        by_goal.setdefault(entry.goal_id, []).append(entry)

    metrics: dict[str, GoalMetrics] = {}
    for goal in dataset.goals:
        if goal.goal_id in skip:
            continue
        metrics[goal.goal_id] = compute_goal(goal, by_goal.get(goal.goal_id, []), params, as_of)
    return metrics
