"""Offline quantile forecasts for Exophase GTA VI trophy earn rates."""

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

LAUNCH = datetime(2026, 11, 19, tzinfo=timezone.utc)
Z = (-1.645, -0.674, 0, 0.674, 1.645)
ASYMPTOTE_MULTIPLIERS = (1.0, 1.15, 1.35, 1.6, 2.0, 2.6, 3.5, 5.0, 8.0)


def clamp(value, low=0.01, high=99.99):
    return min(high, max(low, value))


def logit(rate):
    rate = clamp(rate)
    return math.log(rate / (100 - rate))


def inv_logit(value):
    if value < 0:
        odds = math.exp(value)
        return 100 * odds / (1 + odds)
    return 100 / (1 + math.exp(-value))


def round4(value):
    scaled = value * 10000
    whole = math.floor(scaled)
    whole += scaled - whole >= 0.5
    return whole // 10000 if whole % 10000 == 0 else whole / 10000


def quantiles(center, spread):
    return [round4(clamp(inv_logit(center + z * spread), 0, 100)) for z in Z]


def hours_since_launch(value):
    if isinstance(value, str):
        try:
            date = datetime.fromisoformat(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            return (date - LAUNCH).total_seconds() / 3600
        except ValueError:
            pass
    return None


def number(value):
    if type(value) in (int, float) and math.isfinite(value):
        return value
    return None


def as_list(value):
    return value if isinstance(value, list) else []


def distinct_states(history, trophy_count):
    states = []
    previous = None
    for read in history:
        if not isinstance(read, dict):
            continue
        players = number(read.get("players_tracked"))
        rates = tuple(map(number, as_list(read.get("rates"))[:trophy_count]))
        rates += (None,) * (trophy_count - len(rates))
        signature = (players, rates)
        if signature != previous:
            hour = hours_since_launch(read.get("slot"))
            if hour is None:
                hour = hours_since_launch(read.get("at"))
            states.append((hour, players, rates))
            previous = signature
    # The final raw read has the same counts and rates as the final state.
    return states


def log_hour(hour):
    return math.log(max(hour, 0.05))


def fit_line(points):
    """Return the intercept and slope of an ordinary least-squares line."""
    if len(points) < 3:
        return None
    x_mean = math.fsum(x for x, _ in points) / len(points)
    y_mean = math.fsum(y for _, y in points) / len(points)
    variance = math.fsum((x - x_mean) ** 2 for x, _ in points)
    if variance == 0:
        return None
    slope = math.fsum((x - x_mean) * (y - y_mean) for x, y in points) / variance
    return y_mean - slope * x_mean, slope


def saturating_fit(observations, last_rate, target):
    best = None
    for asymptote in (*[min(99.5, last_rate * m) for m in ASYMPTOTE_MULTIPLIERS], 99.5):
        points = [
            (log_hour(hour), math.log(asymptote / rate - 1))
            for hour, rate in observations if rate < asymptote
        ]
        fit = fit_line(points)
        if fit is None:
            continue
        intercept, slope = fit
        if slope >= 0:
            continue
        residual = math.sqrt(
            math.fsum((y - (intercept + slope * x)) ** 2 for x, y in points) / len(points)
        )
        if best is None or residual < best[1]:
            prediction = asymptote * inv_logit(-(intercept + slope * target)) / 100
            best = prediction, residual
    return best if best is not None else (last_rate, 0.5)


def local_trend(observations, last_rate, checkpoint, target):
    points = [
        (log_hour(hour), logit(rate))
        for hour, rate in observations if checkpoint - hour <= 24
    ]
    fit = fit_line(points)
    if fit is None:
        return last_rate
    intercept, slope = fit
    end = points[-1][0]
    fitted_end = intercept + slope * end
    return inv_logit(fitted_end + 0.5 * clamp(slope, -1.5, 1.5) * (target - end))


def refresh_volatility(series):
    trophy_volatilities = []
    for rates in series:
        changes = [
            abs(logit(after) - logit(before))
            for before, after in zip(rates, rates[1:])
            if before is not None and after is not None
        ]
        if len(changes) >= 2:
            trophy_volatilities.append(median(changes))
    return clamp(median(trophy_volatilities), 0.15, 0.8) if trophy_volatilities else 0.3


def forecast(case):
    trophies = as_list(case.get("trophies"))
    states = distinct_states(as_list(case.get("history")), len(trophies))
    rows = []
    if states:
        _, last_players, last_rates = states[-1]
        known_last_rates = [rate for rate in last_rates if rate is not None]
        global_rate = median(known_last_rates) if known_last_rates else 0.5
        series = list(zip(*(rates for _, _, rates in states)))

    if len(states) >= 3:
        horizon = number(case.get("horizon_minutes"))
        checkpoint = hours_since_launch(case.get("at"))
        target_hour = hours_since_launch(case.get("target"))
        if checkpoint is None:
            checkpoint = next((h for h, _, _ in reversed(states) if h is not None), 0)
        if horizon is None:
            horizon = (target_hour - checkpoint) * 60 if target_hour is not None else 0
        horizon = max(0, horizon)
        if target_hour is None:
            target_hour = checkpoint + horizon / 60
        target = log_hour(target_hour)
        horizon_spread = 0.5 * math.sqrt(horizon / 1440)
        volatility = refresh_volatility(series)

    for index, trophy in enumerate(trophies):
        if not isinstance(trophy, dict) or "id" not in trophy:
            continue
        if not states:
            values = quantiles(logit(1), 1.2)
        else:
            last_rate = last_rates[index] or 0
            rates = series[index]
            if last_rate >= 99.5:
                values = [100] * len(Z)
            elif not any(rate is not None and rate > 0 for rate in rates):
                values = quantiles(logit(global_rate), 1.2)
            elif len(states) < 3:
                # Expected earners and tracked players jump by different factors.
                players = last_players if last_players and last_players > 0 else 1
                old_earners = last_rate * players / 100
                new_earners = old_earners * 1.338
                new_players = players * 6.06
                values = quantiles(logit(100 * new_earners / new_players), 0.9)
            else:
                observations = [
                    (hour, rate) for (hour, _, _), rate in zip(states, rates)
                    if hour is not None and rate is not None and rate > 0
                ]
                saturated, residual = saturating_fit(observations, last_rate, target)
                linear = local_trend(observations, last_rate, checkpoint, target)
                persistence = last_rate or 0.02
                center = 0.5 * logit(saturated) + 0.3 * logit(linear) + 0.2 * logit(persistence)
                residual = clamp(residual, 0.15, 0.8)
                spread = 0.5 * math.sqrt(horizon_spread**2 + residual**2 + volatility**2)
                values = quantiles(center, clamp(spread, 0.30, 1.2))
        rows.append({"id": trophy["id"], "q": values})
    return {"trophies": rows}


def main():
    input_dir = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
    output_dir = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))
    output_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted(input_dir.glob("*.in")):
        try:
            case = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeError, ValueError):
            case = {}
        result = forecast(case if isinstance(case, dict) else {})
        payload = json.dumps(result, separators=(",", ":"), allow_nan=False)
        (output_dir / f"{path.stem}.out").write_text(payload + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
