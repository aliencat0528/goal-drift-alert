"""預測層：bootstrap Monte Carlo。

為什麼是 bootstrap 而不是常態假設：日增量是稀疏的小整數（很多天是 0，偶爾 4），
形狀離常態很遠，套常態會把「連續三天 0」算成幾乎不可能，然後在它發生時大驚小怪。
重抽自己的歷史不需要假設任何分佈——**你的資料長什麼樣，模擬就長什麼樣**。

輸出的 P 天生就是機率，不需要再校準（← `docs/DECISION-FLOW.md` V 公式表）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from compute.metrics import GoalMetrics
from core.config import Params


@dataclass
class Forecast:
    """一次 Monte Carlo 的結果。`ready=False` 時所有數字都是 None——

    資料不足時給一個「大概」的機率，比不給更糟：它會被當成真的。
    """

    ready: bool
    points: int
    needed: int
    p_success: float | None = None
    p_miss: float | None = None
    expected_final: float | None = None
    interval: tuple[float, float] | None = None
    completion_span: tuple[date, date] | None = None
    p_completes_within_horizon: float | None = None
    runs: int = 0

    @property
    def short_by(self) -> int:
        return max(self.needed - self.points, 0)

    def calibrating_text(self) -> str:
        return f"校準中，還差 {self.short_by} 天（已有 {self.points}／需要 {self.needed}）"


def _rng(params: Params) -> np.random.Generator:
    """固定種子：同一份資料重跑要得到同一張決策卡，否則回放比不出差異。"""
    return np.random.default_rng(int(params.forecast.random_seed))


def _pool(metrics: GoalMetrics, params: Params) -> np.ndarray:
    window = int(params.forecast.bootstrap_window_days)
    return metrics.deltas[-window:] if metrics.deltas.size else metrics.deltas


def _simulate(pool: np.ndarray, days: int, runs: int, rng: np.random.Generator) -> np.ndarray:
    """回傳 (runs, days) 的累積量矩陣。"""
    draws = rng.choice(pool, size=(runs, days), replace=True)
    return np.cumsum(draws, axis=1)


def forecast_goal(metrics: GoalMetrics, params: Params) -> Forecast:
    """對「維持現狀」情境跑一次 Monte Carlo。"""
    needed = int(params.cold_start.min_points.monte_carlo)
    points = metrics.points
    pool = _pool(metrics, params)

    if points < needed or pool.size == 0 or metrics.remaining_days <= 0:
        return Forecast(ready=False, points=points, needed=needed)

    runs = int(params.forecast.monte_carlo_runs)
    horizon_extra = int(params.forecast.extension_horizon_days)
    horizon = metrics.remaining_days + horizon_extra
    cumulative_paths = metrics.cumulative + _simulate(pool, horizon, runs, _rng(params))

    at_deadline = cumulative_paths[:, metrics.remaining_days - 1]
    p_success = float((at_deadline >= metrics.goal.target).mean())

    confidence = float(params.forecast.confidence)
    low_q = (1 - confidence) / 2 * 100
    high_q = (1 - (1 - confidence) / 2) * 100
    interval = (
        float(np.percentile(at_deadline, low_q)),
        float(np.percentile(at_deadline, high_q)),
    )

    reached = cumulative_paths >= metrics.goal.target
    ever = reached.any(axis=1)
    completion_span = None
    if ever.any():
        first_day = reached[ever].argmax(axis=1)  # 0-based：0 代表今天就達標
        low_day = int(np.percentile(first_day, low_q))
        high_day = int(np.percentile(first_day, high_q))
        completion_span = (
            metrics.as_of + timedelta(days=low_day),
            metrics.as_of + timedelta(days=high_day),
        )

    return Forecast(
        ready=True,
        points=points,
        needed=needed,
        p_success=p_success,
        p_miss=1.0 - p_success,
        expected_final=float(at_deadline.mean()),
        interval=interval,
        completion_span=completion_span,
        p_completes_within_horizon=float(ever.mean()),
        runs=runs,
    )


def scenario_probability(
    metrics: GoalMetrics,
    params: Params,
    target: float | None = None,
    extra_days: int = 0,
) -> float | None:
    """某個「如果」的達成機率：改目標（`target`）或延期（`extra_days`）。

    決策卡的三個選項必須用**同一台模擬器**算，否則選項之間的機率不可比，
    而不可比的選項等於沒有選項。
    """
    pool = _pool(metrics, params)
    days = metrics.remaining_days + max(extra_days, 0)
    if pool.size == 0 or days <= 0:
        return None

    goal_target = metrics.goal.target if target is None else target
    runs = int(params.forecast.monte_carlo_runs)
    paths = metrics.cumulative + _simulate(pool, days, runs, _rng(params))
    return float((paths[:, days - 1] >= goal_target).mean())


def extension_days_for_current_pace(metrics: GoalMetrics) -> int | None:
    """要延到哪天，才是「照現在的速度做得完」。

    延期選項不能隨便挑一個日期——挑出來的日期必須有意義，
    而唯一有意義的日期是「required rate 掉回你現在的速度」的那一天。
    """
    if metrics.run_rate <= 0 or metrics.gap <= 0:
        return None
    days_needed = int(np.ceil(metrics.gap / metrics.run_rate))
    return max(days_needed - metrics.remaining_days, 0)


def suggested_target(metrics: GoalMetrics) -> float | None:
    """照現在速度做得到的目標值，取整到比較好講的數字。

    這是「認賠出場」那個選項的具體內容——**改目標是風險管理的正當動作，不是失敗**。
    """
    if metrics.run_rate <= 0:
        return None
    reachable = metrics.cumulative + metrics.run_rate * metrics.remaining_days
    if reachable <= metrics.cumulative:
        return None
    step = 5 if reachable >= 20 else 1
    rounded = int(reachable // step * step)
    return float(max(rounded, int(metrics.cumulative) + 1))
