"""偵測層：把指標序列變成候選警示。

M1 上線三個偵測器：**D2 計數**、**D4 累積 pacing**、**D5 變點**。
D1 季節殘差要 `statsmodels`（列在 M2 依賴）且需要 6 週資料才估得出週效應；
D3 比率型需要漏斗分母，而 M1 的 `progress.csv` schema 裡沒有分母欄位——
兩者都不是不做，是**現在做出來的東西無法驗證**（← `prepare.md` AG-008）。

**D5 永遠與其他並聯**：D1–D4 問「今天偏離正常嗎」，只有 D5 問「正常本身變了嗎」。
後者是前者結構上抓不到的——滾動基線會慢慢把新常態吸收進去，然後安靜下來。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

import numpy as np
from scipy import stats

from compute.forecast import Forecast, forecast_goal
from compute.metrics import GoalMetrics, historical_best_rate, rolling_mean
from core.config import Params

# 四個觸發（← docs/DECISION-FLOW.md）。順序即嚴重度，去重時取第一個當標題
TRIGGERS = ("feasibility_flip", "trend_reversal", "buffer_depletion", "silence")

TRIGGER_LABELS = {
    "feasibility_flip": "可行性翻轉",
    "trend_reversal": "趨勢反轉",
    "buffer_depletion": "緩衝耗盡",
    "silence": "靜默期",
}


@dataclass
class Candidate:
    """一則候選警示。**候選不等於會發**——發不發是 `gate` 的事。"""

    goal_id: str
    trigger: str
    detector: str
    headline: str
    p_risk: float | None
    evidence: list[str] = field(default_factory=list)
    calibrating: str | None = None
    detail: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        return TRIGGER_LABELS[self.trigger]

    @property
    def severity_rank(self) -> int:
        return TRIGGERS.index(self.trigger)


@dataclass
class DayState:
    """回放某一天的狀態。三個偵測器都要問「這是第幾天了」，所以先把每天算出來。"""

    day: date
    cumulative: float
    required_rate: float | None
    run_rate: float
    hist_best: float | None
    pressure: float | None


def replay_states(metrics: GoalMetrics, params: Params) -> list[DayState]:
    """把目標的每一天重算一次。

    「首次超過」與「連續 N 天」這兩件事沒有歷史狀態就答不出來，
    而答不出來的話決策卡只能說「現在很糟」，不能說「從哪天開始糟的」——
    後者才是使用者判斷「這則對不對」的依據。
    """
    goal = metrics.goal
    window = int(params.drift.run_rate_window_days)
    states: list[DayState] = []

    for i, day in enumerate(metrics.dates):
        prefix = metrics.deltas[: i + 1]
        cumulative = float(prefix.sum())
        gap = max(goal.target - cumulative, 0.0)
        remaining = goal.remaining_days(day)
        required = gap / remaining if remaining > 0 else None
        recent = prefix[-window:]
        run_rate = float(recent.mean()) if recent.size else 0.0
        hist_best, _ = historical_best_rate(prefix, params)

        if required is None:
            pressure = None
        elif run_rate > 0:
            pressure = required / run_rate
        else:
            pressure = math.inf if required > 0 else 0.0

        states.append(DayState(day, cumulative, required, run_rate, hist_best, pressure))
    return states


# ── D4：累積 pacing ────────────────────────────────────────────


def detect_feasibility_flip(
    metrics: GoalMetrics, states: list[DayState], forecast: Forecast, params: Params
) -> Candidate | None:
    """required rate 超過歷史最佳 P90 的那一刻。

    **這是唯一真正需要立刻知道的時刻**——它是還來得及改目標的最後窗口。
    """
    if metrics.closed or metrics.required_rate is None or not metrics.hist_best_rate:
        return None
    if metrics.required_rate <= metrics.hist_best_rate:
        return None

    flip_days = [
        s.day for s in states if s.required_rate and s.hist_best and s.required_rate > s.hist_best
    ]
    first_flip = flip_days[0] if flip_days else metrics.as_of
    streak = (metrics.as_of - first_flip).days + 1
    multiple = metrics.required_rate / metrics.hist_best_rate

    evidence = [
        f"required {metrics.required_rate:.2f}／天 > 歷史最佳 P90 "
        f"{metrics.hist_best_rate:.2f}／天（{multiple:.0%}）",
        f"首次超過是 {first_flip}，已持續 {streak} 天",
        f"歷史最佳的取法：{metrics.hist_best_basis}",
    ]
    if metrics.sustained_days_needed():
        evidence.append(
            f"就算從今天起維持歷史最佳，也要 {metrics.sustained_days_needed()} 天，"
            f"但只剩 {metrics.remaining_days} 天"
        )

    return Candidate(
        goal_id=metrics.goal.goal_id,
        trigger="feasibility_flip",
        detector="D4",
        headline="required 已超過你做過的最快速度",
        p_risk=forecast.p_miss,
        evidence=evidence,
        calibrating=None if forecast.ready else forecast.calibrating_text(),
        detail={"first_flip": first_flip, "streak_days": streak, "multiple": multiple},
    )


def detect_buffer_depletion(
    metrics: GoalMetrics, states: list[DayState], forecast: Forecast, params: Params
) -> Candidate | None:
    """壓力係數（required ÷ 目前速度）連續 N 天在黃燈之上。"""
    if metrics.closed or metrics.pressure is None:
        return None

    yellow = float(params.drift.pressure_yellow)
    needed = int(params.drift.pressure_consecutive_days)
    if metrics.pressure < yellow:
        return None

    streak = 0
    for state in reversed(states):
        if state.pressure is not None and state.pressure >= yellow:
            streak += 1
        else:
            break
    if streak < needed:
        return None

    pressure_text = (
        "∞（目前速度為 0）" if math.isinf(metrics.pressure) else f"{metrics.pressure:.2f}"
    )
    evidence = [
        f"壓力係數 {pressure_text} ≥ 黃燈 {yellow}，已連續 {streak} 天",
        f"目前 {metrics.run_rate:.2f}／天，required {metrics.required_rate:.2f}／天",
    ]
    if metrics.pace_ratio is not None:
        evidence.append(
            f"pace ratio {metrics.pace_ratio:.2f}"
            f"（進度 {metrics.attainment:.0%} vs 時間 {metrics.elapsed_ratio:.0%}）"
        )

    return Candidate(
        goal_id=metrics.goal.goal_id,
        trigger="buffer_depletion",
        detector="D4",
        headline=f"緩衝已耗掉，維持現速做不完（連續 {streak} 天）",
        p_risk=forecast.p_miss,
        evidence=evidence,
        calibrating=None if forecast.ready else forecast.calibrating_text(),
        detail={"streak_days": streak, "pressure": metrics.pressure},
    )


# ── D5：變點 ───────────────────────────────────────────────────


def _ewma_signal(values: np.ndarray, params: Params) -> tuple[bool, dict]:
    """EWMA 控制圖，只看**向下**穿出下界。

    向上穿出是「今天特別拚」，那不需要打斷你。
    對稱地報兩邊在統計上比較漂亮，但一半的訊號沒有行動可做——依 SRE 原則就不該發。
    """
    lam = float(params.detector.ewma["lambda"])
    limit = float(params.detector.ewma.L)
    center = float(values.mean())
    sigma = float(values.std(ddof=1)) if values.size > 1 else 0.0
    if sigma == 0:
        return False, {"reason": "序列沒有變異，控制圖無意義"}

    z = center
    for index, value in enumerate(values, start=1):
        z = lam * value + (1 - lam) * z
        spread = sigma * math.sqrt(lam / (2 - lam) * (1 - (1 - lam) ** (2 * index)))
        lower = center - limit * spread
    return z < lower, {"ewma": z, "lower": lower, "center": center, "lambda": lam, "L": limit}


def _cusum_signal(values: np.ndarray, params: Params) -> tuple[bool, dict]:
    """CUSUM 下側累積和。抓的是「每天只差一點點、但一直差」——正是偏移的形狀。"""
    k = float(params.detector.cusum.k)
    h = float(params.detector.cusum.h)
    center = float(values.mean())
    sigma = float(values.std(ddof=1)) if values.size > 1 else 0.0
    if sigma == 0:
        return False, {"reason": "序列沒有變異，CUSUM 無意義"}

    negative = 0.0
    peak = 0.0
    for value in values:
        negative = max(0.0, negative + (center - value) - k * sigma)
        peak = max(peak, negative)
    return peak > h * sigma, {"cusum": peak, "limit": h * sigma, "k": k, "h": h}


def _western_electric_run(values: np.ndarray, params: Params) -> tuple[bool, dict]:
    """連續 N 點落在中心線同一側（下側）。版本有用 7／8／9，本專案固定 8 並在報告標明。"""
    run_length = int(params.detector.western_electric.run_length)
    center = float(values.mean())
    if values.size < run_length:
        return False, {"run_length": run_length, "center": center, "streak": 0}

    streak = 0
    for value in reversed(values):
        if value < center:
            streak += 1
        else:
            break
    return streak >= run_length, {"run_length": run_length, "center": center, "streak": streak}


def detect_trend_reversal(
    metrics: GoalMetrics, forecast: Forecast, params: Params
) -> Candidate | None:
    """D5：run rate 出現階躍下降——**你的產出掉了，但你沒發現**。"""
    if metrics.closed:
        return None

    needed = int(params.cold_start.min_points.ewma)
    if metrics.points < needed:
        return None

    # 用滾動平均而不是原始日增量：日增量的雜訊會讓控制圖每週都叫一次，
    # 而我們要抓的是「這條線的水位變了」，不是「今天比較少」
    window = int(params.detector.best_rate_window_days)
    series = rolling_mean(metrics.deltas, window)
    if series.size < needed - window:
        return None

    ewma_hit, ewma_detail = _ewma_signal(series, params)
    cusum_hit, cusum_detail = _cusum_signal(series, params)
    we_hit, we_detail = _western_electric_run(series, params)
    if not (ewma_hit or cusum_hit or we_hit):
        return None

    evidence = []
    if ewma_hit:
        evidence.append(
            f"EWMA（λ={ewma_detail['lambda']}）{ewma_detail['ewma']:.2f} "
            f"跌破下界 {ewma_detail['lower']:.2f}"
        )
    if cusum_hit:
        evidence.append(
            f"CUSUM 下側累積 {cusum_detail['cusum']:.2f} > 界限 {cusum_detail['limit']:.2f}"
        )
    if we_hit:
        evidence.append(
            f"Western Electric：連續 {we_detail['streak']} 點低於中心線"
            f"（規則用 run_length={we_detail['run_length']}）"
        )
    evidence.append(
        f"中心線 {ewma_detail.get('center', we_detail['center']):.2f}／天，"
        f"目前 {metrics.run_rate:.2f}／天"
    )

    return Candidate(
        goal_id=metrics.goal.goal_id,
        trigger="trend_reversal",
        detector="D5",
        headline="產出水位往下移了，不是單日波動",
        p_risk=forecast.p_miss,
        evidence=evidence,
        calibrating=None if forecast.ready else forecast.calibrating_text(),
        detail={"ewma": ewma_detail, "cusum": cusum_detail, "western_electric": we_detail},
    )


def detect_silence(metrics: GoalMetrics, forecast: Forecast, params: Params) -> Candidate | None:
    """靜默期：抓「這個目標已經死了，但你還沒承認」。"""
    if metrics.closed or metrics.silence_threshold is None:
        return None
    if metrics.silence_days <= metrics.silence_threshold:
        return None

    percentile = float(params.drift.silence_percentile) * 100
    evidence = [
        f"已 {metrics.silence_days} 天沒有任何進展",
        f"你自己的歷史間隔 P{percentile:.0f} 是 {metrics.silence_threshold:.1f} 天",
        f"剩 {metrics.remaining_days} 天，還差 {metrics.gap:g}",
    ]
    return Candidate(
        goal_id=metrics.goal.goal_id,
        trigger="silence",
        detector="D5",
        headline=f"已 {metrics.silence_days} 天沒動，超過你自己的正常間隔",
        p_risk=forecast.p_miss,
        evidence=evidence,
        calibrating=None if forecast.ready else forecast.calibrating_text(),
        detail={"silence_days": metrics.silence_days, "threshold": metrics.silence_threshold},
    )


# ── D2：計數型偏離（當作其他觸發的佐證，不單獨成一則）─────────────


def count_evidence(metrics: GoalMetrics, params: Params) -> str | None:
    """近期產出量對照基線期望值的單尾檢定。

    它不單獨成一則警示：「近 7 天比平常少」本身沒有行動可做，
    要接到「所以做不完了」才有。所以 D2 在這裡的角色是**把統計證據掛到別的觸發上**。
    """
    recent_days = int(params.detector.count.recent_days)
    alpha = float(params.detector.count.alpha)
    threshold = float(params.detector.count.poisson_threshold)

    if metrics.deltas.size < recent_days * 2:
        return None
    baseline = metrics.deltas[:-recent_days]
    recent = metrics.deltas[-recent_days:]
    mu = float(baseline.mean())
    if mu <= 0:
        return None

    observed = float(recent.sum())
    expected = mu * recent_days
    variance = float(baseline.var(ddof=1)) if baseline.size > 1 else mu

    if mu < threshold and variance <= mu:
        p_value = float(stats.poisson.cdf(observed, expected))
        model = "Poisson exact"
    else:
        # 過度離散（變異數 > 平均）時用 Poisson 會低估雜訊，於是把正常波動當成異常
        dispersion = max(variance - mu, 1e-9)
        r = mu**2 / dispersion * recent_days
        p = r / (r + expected)
        p_value = float(stats.nbinom.cdf(observed, r, p))
        model = "Negative Binomial／過度離散"

    if p_value > alpha:
        return None
    return (
        f"近 {recent_days} 天產出 {observed:g}，基線期望 {expected:.1f}"
        f"（{model}，單尾 p={p_value:.3f}）"
    )


def detect_goal(metrics: GoalMetrics, params: Params) -> tuple[list[Candidate], Forecast]:
    """跑完一個目標的所有偵測器。"""
    forecast = forecast_goal(metrics, params)
    states = replay_states(metrics, params)

    candidates = [
        detect_feasibility_flip(metrics, states, forecast, params),
        detect_trend_reversal(metrics, forecast, params),
        detect_buffer_depletion(metrics, states, forecast, params),
        detect_silence(metrics, forecast, params),
    ]
    found = [c for c in candidates if c is not None]

    support = count_evidence(metrics, params)
    if support:
        for candidate in found:
            candidate.evidence.append(f"D2 佐證：{support}")

    found.sort(key=lambda c: c.severity_rank)
    return found, forecast


def detect_all(
    metrics_by_goal: dict[str, GoalMetrics], params: Params
) -> tuple[list[Candidate], dict[str, Forecast]]:
    candidates: list[Candidate] = []
    forecasts: dict[str, Forecast] = {}
    for goal_id, metrics in metrics_by_goal.items():
        found, forecast = detect_goal(metrics, params)
        candidates.extend(found)
        forecasts[goal_id] = forecast
    return candidates, forecasts
