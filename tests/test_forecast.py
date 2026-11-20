import json
import math
import os
import random
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
KIT_INPUT = REPO.parent / "gta6-trophy-rarity-forecast-01-kit" / "input"
LEVELS = (0.05, 0.25, 0.5, 0.75, 0.95)
Z = (-1.645, -0.674, 0, 0.674, 1.645)
LAUNCH = datetime(2026, 11, 19, tzinfo=timezone.utc)
SEEDS = (7, 23, 61)


def run_forecaster(input_dir, output_dir):
    env = dict(os.environ, MAKEFUN_INPUT_DIR=str(input_dir), MAKEFUN_OUTPUT_DIR=str(output_dir))
    start = time.perf_counter()
    subprocess.run(
        [sys.executable, "-P", "-s", str(REPO / "main.py")],
        env=env, check=True, capture_output=True, timeout=8,
    )
    return time.perf_counter() - start


def stamp(hour):
    return (LAUNCH + timedelta(hours=hour)).isoformat()


def synthetic_case(seed):
    rng = random.Random(seed)
    checkpoint, target = 59.67, 168.17
    curves = [
        (rng.uniform(0.8, 90), rng.uniform(35, 180), rng.uniform(0.8, 1.9))
        for _ in range(54)
    ]
    growth = rng.uniform(0.85, 1.3)

    def page(hour):
        players = int(638 * (1 + hour) ** growth)
        earners = [players]
        for ceiling, midpoint, slope in curves:
            share = ceiling / (1 + (midpoint / max(hour, 0.05)) ** slope)
            earners.append(round(players * share / 100))
        return {
            "players_tracked": players,
            "trophies_earned": sum(earners),
            "rates": [round(100 * earned / players, 2) for earned in earners],
        }

    history = []
    refreshed = page(0)
    next_refresh = rng.randint(12, 24)
    for slot in range(math.ceil(target * 6)):
        if slot == next_refresh:
            refreshed = page(slot / 6)
            next_refresh += rng.randint(12, 24)
        hour = slot / 6
        if hour < checkpoint:
            history.append(dict(refreshed, slot=stamp(hour), at=stamp(hour)))

    case = {
        "schema": "makefun/gta6-trophies-case/v1",
        "id": "synthetic",
        "at": stamp(checkpoint),
        "target": stamp(target),
        "horizon_minutes": round((target - checkpoint) * 60),
        "levels": LEVELS,
        "trophies": [{"id": i} for i in range(1, 56)],
        "history": history,
    }
    return case, refreshed["rates"]


def logit(rate):
    rate = max(0.01, min(99.99, rate))
    return math.log(rate / (100 - rate))


def persistence(case):
    spread = 0.5 * math.sqrt(case["horizon_minutes"] / 1440)
    return [
        [math.floor(1000000 / (1 + math.exp(-logit(rate) - z * spread)) + 0.5) / 10000
         for z in Z]
        for rate in case["history"][-1]["rates"]
    ]


def pinball(actual, forecasts):
    terms = []
    for rate, values in zip(actual, forecasts, strict=True):
        for level, value in zip(LEVELS, values, strict=True):
            error = logit(rate) - logit(value)
            terms.append(2 * max(level * error, (level - 1) * error))
    return math.fsum(terms) / len(terms)


class ForecastTests(unittest.TestCase):
    def valid_output(self, payload, expected_ids=range(1, 56)):
        self.assertLessEqual(len(payload), 65536)
        result = json.loads(payload)
        self.assertEqual(set(result), {"trophies"})
        rows = result["trophies"]
        self.assertCountEqual([row["id"] for row in rows], expected_ids)
        for row in rows:
            self.assertEqual(set(row), {"id", "q"})
            values = row["q"]
            self.assertEqual(len(values), 5)
            self.assertEqual(values, sorted(values))
            for value in values:
                self.assertIn(type(value), (int, float))
                self.assertTrue(math.isfinite(value))
                self.assertTrue(0 <= value <= 100)
        return {row["id"]: row["q"] for row in rows}

    def test_practice_contract_determinism_and_dilution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for case_id in ("p00", "p01"):
                with self.subTest(case=case_id):
                    path = KIT_INPUT / f"{case_id}.in"
                    payload = path.read_bytes()
                    input_dir = root / case_id
                    input_dir.mkdir()
                    (input_dir / path.name).write_bytes(payload)
                    times, forecasts = [], []
                    for attempt in range(2):
                        output_dir = root / f"{case_id}-run-{attempt}"
                        times.append(run_forecaster(input_dir, output_dir))
                        self.assertLess(times[-1], 8)
                        forecasts.append((output_dir / f"{case_id}.out").read_bytes())
                    self.assertEqual(*forecasts)
                    values_by_id = self.valid_output(forecasts[0])
                    case = json.loads(payload)
                    last = case["history"][-1]["rates"]
                    for trophy, rate in zip(case["trophies"], last, strict=True):
                        values = values_by_id[trophy["id"]]
                        if rate >= 99.5:
                            self.assertEqual(values, [100] * 5)
                        else:
                            self.assertLess(values[2], rate)
                    print(f"{case_id} elapsed seconds: {times[0]:.3f}, {times[1]:.3f}")

    def test_final_like_forecasts_beat_house_persistence(self):
        for seed in SEEDS:
            with self.subTest(seed=seed), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                case, actual = synthetic_case(seed)
                (root / "synthetic.in").write_text(json.dumps(case), encoding="utf-8")
                output_dir = root / "out"
                elapsed = run_forecaster(root, output_dir)
                values_by_id = self.valid_output((output_dir / "synthetic.out").read_bytes())
                self.assertEqual(values_by_id[1], [100] * 5)
                loss = pinball(actual, [values_by_id[i] for i in range(1, 56)])
                baseline = pinball(actual, persistence(case))
                print(f"seed {seed}: model {loss:.6f}, persistence {baseline:.6f}, {elapsed:.3f}s")
                self.assertLess(loss, baseline)

    def test_zero_last_rate_keeps_positive_saturating_forecast(self):
        case = {
            "trophies": [{"id": 1}],
            "at": stamp(59.67),
            "target": stamp(168.17),
            "horizon_minutes": 6510,
            "history": [
                {"slot": stamp(hour), "rates": [rate]}
                for hour, rate in [(0, 1), (24, 2), (48, 0)]
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "zero.in").write_text(json.dumps(case), encoding="utf-8")
            output_dir = root / "out"
            run_forecaster(root, output_dir)
            values = self.valid_output((output_dir / "zero.out").read_bytes(), [1])[1]
            self.assertGreater(values[2], 0.02)

    def test_missing_rates_and_empty_history(self):
        cases = {
            "empty": ({"trophies": [{"id": 1}]}, {1: 1}),
            "missing": (
                {"trophies": [{"id": 1}, {"id": 2}, {"id": 3}],
                 "history": [{"rates": [None, 5, 100]}]},
                {1: 52.5, 2: 1.104, 3: 100},
            ),
            "unobserved": (
                {"trophies": [{"id": 1}], "history": [{}]},
                {1: 0.5},
            ),
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "out"
            for name, (case, _) in cases.items():
                (root / f"{name}.in").write_text(json.dumps(case), encoding="utf-8")
            run_forecaster(root, output_dir)
            for name, (_, expected) in cases.items():
                with self.subTest(case=name):
                    output = (output_dir / f"{name}.out").read_bytes()
                    values_by_id = self.valid_output(output, expected)
                    self.assertEqual({i: q[2] for i, q in values_by_id.items()}, expected)


if __name__ == "__main__":
    unittest.main()
