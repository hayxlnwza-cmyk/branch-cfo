"""CI gate: fail the PR if forecast calibration or formula tests drift. python -m engine.ci_gate"""
import json, os, sys
from pathlib import Path

from . import backtest as bt

ROOT = Path(__file__).resolve().parent.parent
seed = json.loads((ROOT / "data" / "seed.json").read_text())
cal = bt.calibration_study(seed["true_params"], n_series=400, train=18)
roll = bt.rolling_backtest(seed["history"], seed["business"]["first_month"], H=3, min_train=15)
LO, HI = 0.65, 0.92  # target 0.80; band reflects estimator noise on short histories
ok = LO <= cal["coverage_80"] <= HI and roll["mape_median"] <= roll["mape_seasonal_naive"] * 1.25
md = f"""### Backtest gate
| metric | value | gate |
|---|---|---|
| calibration coverage 80% ({cal['n_points']} pts) | {cal['coverage_80']:.3f} | {LO}-{HI} |
| rolling coverage 80% (n={roll['n_points']}) | {roll['coverage_80']:.3f} | info |
| MAPE median | {roll['mape_median']:.3f} | <= 1.25 x seasonal-naive ({roll['mape_seasonal_naive']:.3f}) |

**{'PASS' if ok else 'FAIL'}** - synthetic data; checks estimator/calibration, not real-world accuracy.
"""
print(md)
if os.getenv("GITHUB_STEP_SUMMARY"):
    Path(os.environ["GITHUB_STEP_SUMMARY"]).write_text(md)
sys.exit(0 if ok else 1)
