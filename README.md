# GTA VI Trophy Rarity Forecaster

[![make.fun · gta6-trophy-rarity-forecast-01](https://make.fun/badge/gta6-trophy-rarity-forecast-01.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![rank](https://make.fun/badge/gta6-trophy-rarity-forecast-01/aziraiga21/gta6-trophy-rarity-forecast/rank.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![reward](https://make.fun/badge/gta6-trophy-rarity-forecast-01/aziraiga21/gta6-trophy-rarity-forecast/reward.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)

The forecaster collapses repeated Exophase reads into refresh states and decomposes each launch-night earn rate into trophy earners and tracked players. With little history, it forecasts dilution by growing the tracked player count faster than the earner count. With more refreshes, it blends a saturating log-time curve, a damped recent trend, and persistence in logit space. Its five quantiles reflect uncertainty from the forecast horizon, curve residuals, and differences between refreshes. Trophies already at 99.5% or higher stay pinned at 100%.

## Run locally

Use Python 3.13 and point `KIT` to the unpacked competition kit.

```sh
KIT=../gta6-trophy-rarity-forecast-01-kit
mkdir -p out && MAKEFUN_INPUT_DIR="$KIT/input" MAKEFUN_OUTPUT_DIR=out python3 main.py
python3 -m unittest discover -s tests -v
```

## Validation

All three tests passed on the local Python 3.12.3 interpreter. Each practice output had 55 valid rows and was 2,757 bytes. Both cases produced byte-identical outputs across reruns, and all 54 non-pinned medians were below their last observed rates in each case.

| Practice case | First run | Second run |
| --- | ---: | ---: |
| p00 | 0.286 s | 0.195 s |
| p01 | 0.622 s | 0.215 s |

The supplied kit contains the practice inputs. The practice answer rates were unavailable for local pinball scoring. The scores below use seeded synthetic final-like histories with stale reads between refreshes and the house persistence spread.

| Synthetic seed | Model loss | House persistence loss |
| --- | ---: | ---: |
| 7 | 0.165094 | 0.458064 |
| 23 | 0.171027 | 0.492120 |
| 61 | 0.174962 | 0.483962 |
| **Mean** | **0.170361** | **0.478049** |
