"""決策卡。

不是警示，是**決策卡**：症狀、金額、責任、信心、三個選項，而且「不做」也標價。
差別在於警示問「你知道了嗎」，決策卡問「你要選哪個」——
只有後者結束時，使用者手上會多出一個決定。
"""

from __future__ import annotations

from compute.forecast import (
    extension_days_for_current_pace,
    scenario_probability,
    suggested_target,
)
from core.config import Params
from gate.pipeline import KIND_RETARGET, Alert

INDENT = "        "


def _percent(value: float | None) -> str:
    return "—" if value is None else f"{value:.0%}"


def _rate(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}"


def _options(alert: Alert, params: Params) -> list[str]:
    """三個選項。A 認賠、B 硬幹、C 延期——**三個都要標機率，否則選項之間不可比**。

    模擬還沒校準完時三個都標「—」。只給其中一個數字會更糟：
    使用者會拿有數字的那個跟沒數字的那個比，而那正是「不可比」的最壞形式。
    """
    metrics = alert.metrics
    goal = metrics.goal
    ready = alert.forecast.ready
    lines: list[str] = []

    new_target = suggested_target(metrics)
    if new_target and new_target < goal.target:
        rate = (new_target - metrics.cumulative) / max(metrics.remaining_days, 1)
        probability = scenario_probability(metrics, params, target=new_target) if ready else None
        lines.append(
            f"A 改目標為 {new_target:g} — 需 {rate:.2f}／天，達成機率 {_percent(probability)}"
        )

    keep = f"B 維持 {goal.target:g} — 需 {_rate(metrics.required_rate)}／天"
    if metrics.hist_best_rate and metrics.required_rate:
        share = metrics.required_rate / metrics.hist_best_rate
        days = metrics.sustained_days_needed()
        if days:
            keep += f"，等於連續 {days} 天做到歷史最佳的 {share:.0%}"
    keep += f"，機率 {_percent(alert.forecast.p_success)}"
    lines.append(keep)

    extra = extension_days_for_current_pace(metrics)
    if extra:
        new_deadline = goal.deadline.fromordinal(goal.deadline.toordinal() + extra)
        rate = metrics.gap / (metrics.remaining_days + extra)
        probability = scenario_probability(metrics, params, extra_days=extra) if ready else None
        lines.append(
            f"C 延長到 {new_deadline.month}/{new_deadline.day} — 需 {rate:.2f}／天，"
            f"達成機率 {_percent(probability)}"
        )
    if not ready:
        lines.append(f"三個機率都是「—」：{alert.forecast.calibrating_text()}")
    return lines


def _do_nothing(alert: Alert) -> list[str]:
    """「不做」的價格。

    它與其他選項同等視覺權重，因為它是最容易被跳過、卻最該被看見的一項——
    多數人不是選了「維持目標」，而是**沒有選**，然後在月底發現結果。
    """
    metrics = alert.metrics
    forecast = alert.forecast
    lines = []
    if forecast.ready and forecast.expected_final is not None:
        low, high = forecast.interval
        shortfall = max(metrics.goal.target - forecast.expected_final, 0.0)
        lines.append(
            f"照現況走到期末預期 {forecast.expected_final:.1f}"
            f"（{_percent(alert.breakdown.p_risk)} 機率達不到），缺 {shortfall:.1f}"
        )
        lines.append(f"{int(alert.forecast.runs):,} 次模擬的 85% 區間：{low:.1f}–{high:.1f}")
    else:
        lines.append(
            f"目前缺 {metrics.gap:g}，剩 {metrics.remaining_days} 天；"
            f"預測{forecast.calibrating_text()}"
        )
    if alert.kind == KIND_RETARGET:
        # 可救性歸零時 V 必為負（乘以 0 再扣打斷成本），所以要同時給「賭注」——
        # 否則卡片會像在說「這件事不重要」，而它其實是在說「這件事已經來不及」
        lines.append(
            f"V = {alert.breakdown.value:.2f}（可救性已歸零）；"
            f"仍在賠的賭注 = {alert.breakdown.stake:.2f}，排序用它"
        )
    else:
        lines.append(f"這則的期望損失 V = {alert.breakdown.value:.2f}（打斷成本已扣）")
    return lines


def render_card(alert: Alert, params: Params, explain: bool = False) -> str:
    """一張決策卡。`explain=True` 會附上 V 的完整推導（逃生出口之三）。"""
    metrics = alert.metrics
    goal = metrics.goal
    unit = "／天"

    marker = "★" if alert.candidate.trigger == "feasibility_flip" else "•"
    verdict = f"{marker} {alert.candidate.label} — {alert.candidate.headline}"
    if alert.kind == KIND_RETARGET:
        verdict += "\n" + INDENT + "可救性 = 0，本卡不是要你更努力，是建議改目標"

    lines = [
        f"【目標】{goal.name} · 已過 {metrics.elapsed_days} 天（{_percent(metrics.elapsed_ratio)}）"
        f" · 剩 {metrics.remaining_days} 天",
        f"【進度】{metrics.cumulative:g}／{goal.target:g}（{_percent(metrics.attainment)}）"
        f" · pace ratio = {_rate(metrics.pace_ratio)} · SPI = {_rate(metrics.spi)}",
        f"【速率】目前 {metrics.run_rate:.2f}{unit}；required {_rate(metrics.required_rate)}{unit}",
    ]
    if metrics.hist_best_rate:
        lines.append(f"{INDENT}你的歷史最佳（P90）是 {metrics.hist_best_rate:.2f}{unit}")
    lines.append(f"【判定】{verdict}")

    evidence = alert.all_evidence()
    if evidence:
        lines.append(f"【證據】{evidence[0]}")
        lines.extend(f"{INDENT}{line}" for line in evidence[1:])

    options = _options(alert, params)
    if options:
        lines.append(f"【選項】{options[0]}")
        lines.extend(f"{INDENT}{line}" for line in options[1:])

    nothing = _do_nothing(alert)
    lines.append(f"【不做】{nothing[0]}")
    lines.extend(f"{INDENT}{line}" for line in nothing[1:])

    if explain:
        derivation = alert.breakdown.as_lines()
        lines.append(f"【推導】{derivation[0]}")
        lines.extend(f"{INDENT}{line}" for line in derivation[1:])

    lines.append("【回饋】[ 已處理 ]  [ 不用理 ]  [ 太晚了 ]　　※ 沒有「已讀」，已讀學不到東西")
    return "\n".join(lines)


def render_cards(alerts: list[Alert], params: Params, explain: bool = False) -> str:
    return "\n\n".join(render_card(alert, params, explain) for alert in alerts)
