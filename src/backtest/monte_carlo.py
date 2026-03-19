"""
src/backtest/monte_carlo.py  —  AlphaZero Capital
══════════════════════════════════════════════════
Monte Carlo Stress Testing Engine

Answers: "What is the worst realistic outcome for this strategy?"

Methods:
  1. Return Shuffling (Bootstrap)     — randomly shuffles historical returns N times
  2. Parameter Variation              — tests strategy across param ranges
  3. Drawdown Distribution            — distribution of max drawdown over N paths
  4. VaR / CVaR                       — Value-at-Risk at 95% and 99% confidence
  5. Scenario Shocks                  — replays known Indian market crises

Usage:
    mc = MonteCarloEngine(returns=historical_returns, n_simulations=5000)
    report = mc.run_all()
    # report contains: var_95, cvar_95, worst_drawdown_pct, prob_ruin, ...

Results saved to: logs/monte_carlo_results.json
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from ..utils.stats import (
    sharpe, max_drawdown_from_returns, win_rate,
    profit_factor, full_metrics
)

logger = logging.getLogger("MonteCarlo")

_LOG_DIR   = Path(__file__).resolve().parents[2] / "logs"
_LOG_DIR.mkdir(exist_ok=True)
_OUT_FILE  = str(_LOG_DIR / "monte_carlo_results.json")

# ── Known Indian market shock scenarios ───────────────────────────────────────
# Format: (name, description, daily_return_shock, duration_days)
_SCENARIOS: List[Tuple[str, str, float, int]] = [
    ("COVID_2020",       "COVID crash Mar 2020",           -0.038, 22),
    ("DEMONETISATION",   "Demonetisation Nov 2016",        -0.018, 30),
    ("LEHMAN_2008",      "Global Financial Crisis 2008",   -0.025, 45),
    ("BUDGET_SHOCK",     "Union Budget negative reaction", -0.022, 5),
    ("RBI_RATE_HIKE",    "Aggressive RBI rate hike",       -0.012, 10),
    ("FII_SELLOFF",      "FII mass selloff episode",        -0.020, 15),
    ("CHINA_CONTAGION",  "China market contagion",          -0.015, 8),
    ("INR_CRISIS",       "INR/USD crisis (>85)",            -0.010, 20),
    ("COMMODITY_SPIKE",  "Crude oil spike >$120/bbl",       -0.008, 12),
    ("GLOBAL_RALLY",     "Post-crisis recovery rally",      +0.025, 30),
]


class MonteCarloEngine:
    """
    Monte Carlo stress testing for trading strategies.

    Args:
        returns        : historical per-trade returns as fraction of capital
        n_simulations  : number of Monte Carlo paths to generate
        n_periods      : periods per path (defaults to len(returns))
        initial_capital: starting capital for ₹ calculations
        seed           : RNG seed for reproducibility (None = random)
    """

    def __init__(
        self,
        returns:         Sequence[float],
        n_simulations:  int   = 5000,
        n_periods:      Optional[int] = None,
        initial_capital: float = 1_000_000.0,
        seed:           Optional[int] = None,
    ):
        self.returns         = np.asarray(returns, dtype=float)
        self.n_sim           = n_simulations
        self.n_periods       = n_periods or len(self.returns)
        self.initial_capital = initial_capital
        self._rng            = np.random.default_rng(seed)

        if len(self.returns) < 10:
            logger.warning("Monte Carlo: only %d returns — results may be unreliable", len(self.returns))

    # ── Public: full report ───────────────────────────────────────────────────

    def run_all(self, save: bool = True) -> Dict[str, Any]:
        """
        Run all stress tests and return consolidated report.

        Returns dict with keys:
            bootstrap, var, scenario, param_sensitivity,
            summary, generated_at
        """
        logger.info("Monte Carlo: %d simulations × %d periods", self.n_sim, self.n_periods)

        bootstrap   = self.bootstrap()
        var_results = self.value_at_risk()
        scenarios   = self.scenario_shocks()
        param_sens  = self.parameter_sensitivity()

        summary = self._build_summary(bootstrap, var_results)

        report = {
            "generated_at":       datetime.now().isoformat(),
            "n_simulations":      self.n_sim,
            "n_periods":          self.n_periods,
            "historical_returns": int(len(self.returns)),
            "bootstrap":          bootstrap,
            "var":                var_results,
            "scenarios":          scenarios,
            "parameter_sensitivity": param_sens,
            "summary":            summary,
        }

        if save:
            self._save(report)

        logger.info(
            "MC Summary — Worst DD: %.1f%%  VaR(95): %.2f%%  Prob Ruin: %.1f%%  Sharpe p10: %.2f",
            summary["worst_drawdown_pct"],
            summary["var_95_pct"],
            summary["prob_ruin_pct"],
            summary["sharpe_p10"],
        )
        return report

    # ── 1. Bootstrap simulation ───────────────────────────────────────────────

    def bootstrap(self) -> Dict[str, Any]:
        """
        Randomly sample (with replacement) from historical returns N times.
        Each path: sequence of n_periods returns → cumulative equity.

        Returns distribution statistics of end-equity and max drawdown.
        """
        if len(self.returns) == 0:
            return self._empty("bootstrap")

        # Generate all paths at once (vectorised)
        idx      = self._rng.integers(0, len(self.returns), size=(self.n_sim, self.n_periods))
        paths    = self.returns[idx]                          # (n_sim, n_periods)

        # Cumulative equity
        eq_paths = np.cumprod(1 + paths, axis=1)             # (n_sim, n_periods)

        # End equity
        end_eq   = eq_paths[:, -1] * self.initial_capital    # (n_sim,)

        # Max drawdown per path
        peak     = np.maximum.accumulate(eq_paths, axis=1)   # (n_sim, n_periods)
        dd_paths = (peak - eq_paths) / np.where(peak > 0, peak, 1)   # (n_sim, n_periods)
        max_dds  = dd_paths.max(axis=1)                       # (n_sim,) — fraction

        # Sharpe per path
        mean_r   = paths.mean(axis=1)
        std_r    = paths.std(axis=1) + 1e-9
        sharpes  = mean_r / std_r * np.sqrt(252)

        # Probability of ruin: end equity < 50% of initial
        ruin_threshold = 0.5 * self.initial_capital
        prob_ruin = float((end_eq < ruin_threshold).mean())

        return {
            "end_equity": {
                "mean":   round(float(end_eq.mean()), 0),
                "median": round(float(np.median(end_eq)), 0),
                "p5":     round(float(np.percentile(end_eq, 5)), 0),
                "p25":    round(float(np.percentile(end_eq, 25)), 0),
                "p75":    round(float(np.percentile(end_eq, 75)), 0),
                "p95":    round(float(np.percentile(end_eq, 95)), 0),
                "worst":  round(float(end_eq.min()), 0),
                "best":   round(float(end_eq.max()), 0),
            },
            "max_drawdown": {
                "mean_pct":   round(float(max_dds.mean() * 100), 2),
                "median_pct": round(float(np.median(max_dds) * 100), 2),
                "p95_pct":    round(float(np.percentile(max_dds, 95) * 100), 2),
                "worst_pct":  round(float(max_dds.max() * 100), 2),
            },
            "sharpe": {
                "mean":   round(float(sharpes.mean()), 3),
                "p10":    round(float(np.percentile(sharpes, 10)), 3),
                "p50":    round(float(np.median(sharpes)), 3),
                "p90":    round(float(np.percentile(sharpes, 90)), 3),
            },
            "prob_ruin_pct": round(prob_ruin * 100, 2),
            "prob_profitable_pct": round(float((end_eq > self.initial_capital).mean() * 100), 2),
        }

    # ── 2. Value at Risk ──────────────────────────────────────────────────────

    def value_at_risk(self) -> Dict[str, Any]:
        """
        Parametric and historical VaR / CVaR.

        VaR(95%)  = 5th percentile of return distribution
        CVaR(95%) = mean of returns below VaR(95%) — aka Expected Shortfall
        """
        if len(self.returns) < 5:
            return self._empty("var")

        r = self.returns

        # Historical VaR
        var_95_h  = float(np.percentile(r, 5))
        var_99_h  = float(np.percentile(r, 1))
        cvar_95_h = float(r[r <= var_95_h].mean()) if (r <= var_95_h).any() else var_95_h
        cvar_99_h = float(r[r <= var_99_h].mean()) if (r <= var_99_h).any() else var_99_h

        # Parametric VaR (assumes normal distribution)
        mu  = float(r.mean())
        std = float(r.std())
        var_95_p  = mu - 1.645 * std
        var_99_p  = mu - 2.326 * std

        # Per-₹1M capital
        cap = self.initial_capital
        return {
            "historical": {
                "var_95_pct":   round(var_95_h * 100, 3),
                "var_99_pct":   round(var_99_h * 100, 3),
                "cvar_95_pct":  round(cvar_95_h * 100, 3),
                "cvar_99_pct":  round(cvar_99_h * 100, 3),
                "var_95_inr":   round(abs(var_95_h) * cap, 0),
                "var_99_inr":   round(abs(var_99_h) * cap, 0),
                "cvar_95_inr":  round(abs(cvar_95_h) * cap, 0),
            },
            "parametric": {
                "var_95_pct":  round(var_95_p * 100, 3),
                "var_99_pct":  round(var_99_p * 100, 3),
                "mean_return": round(mu * 100, 4),
                "std_return":  round(std * 100, 4),
            },
        }

    # ── 3. Scenario shocks ────────────────────────────────────────────────────

    def scenario_shocks(self) -> List[Dict[str, Any]]:
        """
        Replay each known Indian market crisis by injecting
        shock returns into a baseline equity curve.
        """
        if len(self.returns) < 5:
            return []

        results = []
        baseline_mean = float(self.returns.mean())
        baseline_std  = float(self.returns.std())

        for name, desc, shock, dur in _SCENARIOS:
            # Build a path: baseline returns + shock period
            n_base  = max(0, self.n_periods - dur)
            r_base  = self._rng.normal(baseline_mean, baseline_std, n_base) \
                      if n_base > 0 else np.array([])
            r_shock = np.full(dur, shock)
            path    = np.concatenate([r_base, r_shock])

            eq       = np.cumprod(1 + path) * self.initial_capital
            dd       = max_drawdown_from_returns(path)
            end      = float(eq[-1]) if len(eq) > 0 else self.initial_capital
            pnl      = end - self.initial_capital
            survived = end > self.initial_capital * 0.5

            results.append({
                "scenario":         name,
                "description":      desc,
                "shock_per_day_pct": round(shock * 100, 2),
                "duration_days":    dur,
                "end_equity_inr":   round(end, 0),
                "pnl_inr":          round(pnl, 0),
                "max_drawdown_pct": round(dd * 100, 2),
                "survived":         survived,
            })

        return results

    # ── 4. Parameter sensitivity ──────────────────────────────────────────────

    def parameter_sensitivity(self) -> Dict[str, Any]:
        """
        Test how strategy performance changes when:
        - Transaction costs increase (0 → 30 bps)
        - Win rate degrades (base → -10%, -20%)
        - Average win shrinks
        """
        if len(self.returns) < 10:
            return {}

        r      = self.returns.copy()
        wins   = r[r > 0]
        losses = r[r < 0]

        results: Dict[str, List[Dict]] = {
            "transaction_cost_impact": [],
            "win_rate_degradation":    [],
            "slippage_impact":         [],
        }

        # Transaction cost sweep: 0 to 50 bps
        base_metrics = full_metrics(r)
        for bps in [0, 5, 10, 20, 30, 50]:
            cost = bps / 10_000
            adjusted = r - cost
            m = full_metrics(adjusted)
            results["transaction_cost_impact"].append({
                "cost_bps":    bps,
                "sharpe":      round(m['sharpe'], 3),
                "win_rate":    round(m['win_rate'] * 100, 1),
                "total_return": round(m['total_return'] * 100, 2),
            })

        # Win rate degradation: flip some wins to losses
        for pct_flip in [0, 5, 10, 15, 20]:
            r_copy = r.copy()
            n_flip = int(len(wins) * pct_flip / 100)
            if n_flip > 0 and len(wins) >= n_flip:
                flip_idx = self._rng.choice(np.where(r_copy > 0)[0], n_flip, replace=False)
                for i in flip_idx:
                    r_copy[i] = -abs(r_copy[i])
            m = full_metrics(r_copy)
            results["win_rate_degradation"].append({
                "wins_flipped_pct": pct_flip,
                "new_win_rate":    round(m['win_rate'] * 100, 1),
                "sharpe":          round(m['sharpe'], 3),
                "profit_factor":   round(m['profit_factor'], 3),
            })

        # Slippage impact (separate from commission — affects fill price)
        for slip_bps in [0, 5, 10, 20, 40]:
            slip = slip_bps / 10_000
            # Slippage hurts entries (reduces wins, increases losses)
            r_slip = np.where(r > 0, r - slip, r - slip)
            m = full_metrics(r_slip)
            results["slippage_impact"].append({
                "slippage_bps": slip_bps,
                "sharpe":       round(m['sharpe'], 3),
                "win_rate":     round(m['win_rate'] * 100, 1),
            })

        return results

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _build_summary(self, bootstrap: Dict, var_data: Dict) -> Dict[str, Any]:
        """Distil key numbers for the dashboard and Telegram alerts."""
        worst_dd   = bootstrap.get("max_drawdown", {}).get("worst_pct", 0)
        var_95     = var_data.get("historical", {}).get("var_95_pct", 0)
        prob_ruin  = bootstrap.get("prob_ruin_pct", 0)
        sharpe_p10 = bootstrap.get("sharpe", {}).get("p10", 0)
        end_p5     = bootstrap.get("end_equity", {}).get("p5", self.initial_capital)
        end_p50    = bootstrap.get("end_equity", {}).get("median", self.initial_capital)

        grade = "EXCELLENT" if worst_dd < 10 and sharpe_p10 > 1.0 and prob_ruin < 2 \
           else "GOOD"      if worst_dd < 15 and sharpe_p10 > 0.5 and prob_ruin < 5 \
           else "FAIR"      if worst_dd < 25 and prob_ruin < 15 \
           else "POOR"

        return {
            "worst_drawdown_pct":  worst_dd,
            "var_95_pct":          abs(var_95),
            "prob_ruin_pct":       prob_ruin,
            "prob_profitable_pct": bootstrap.get("prob_profitable_pct", 0),
            "sharpe_p10":          sharpe_p10,
            "median_final_inr":    end_p50,
            "p5_final_inr":        end_p5,
            "grade":               grade,
            "recommendation": {
                "EXCELLENT": "Strategy is robust — suitable for live trading.",
                "GOOD":      "Good risk profile — proceed with half-Kelly sizing.",
                "FAIR":      "Moderate risk — reduce position sizes by 30%.",
                "POOR":      "High risk — do not deploy capital until improved.",
            }[grade],
        }

    @staticmethod
    def _empty(section: str) -> Any:
        return {"error": f"Insufficient data for {section} — need ≥10 returns"}

    def _save(self, report: Dict):
        try:
            tmp = _OUT_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(report, f, indent=2, default=str)
            os.replace(tmp, _OUT_FILE)
            logger.info("Monte Carlo results → %s", _OUT_FILE)
        except Exception as exc:
            logger.warning("MC save failed: %s", exc)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

    # Generate synthetic returns for demo
    rng     = np.random.default_rng(42)
    returns = rng.normal(0.002, 0.015, 500)   # mean +0.2%/trade, std 1.5%

    mc     = MonteCarloEngine(returns=returns, n_simulations=5000, initial_capital=1_000_000)
    report = mc.run_all()

    s = report["summary"]
    print("\n" + "=" * 65)
    print("  MONTE CARLO STRESS TEST RESULTS")
    print("=" * 65)
    print(f"  Worst Drawdown (MC):  {s['worst_drawdown_pct']:.1f}%")
    print(f"  VaR 95% (daily):      {s['var_95_pct']:.2f}%")
    print(f"  Prob of Ruin (<50%):  {s['prob_ruin_pct']:.1f}%")
    print(f"  Prob Profitable:      {s['prob_profitable_pct']:.1f}%")
    print(f"  Sharpe (P10):         {s['sharpe_p10']:.2f}")
    print(f"  Median Final ₹:       ₹{s['median_final_inr']:,.0f}")
    print(f"  Grade:                {s['grade']}")
    print(f"  Verdict:              {s['recommendation']}")

    print("\n  Scenario Shocks:")
    for sc in report["scenarios"]:
        icon = "✅" if sc["survived"] else "❌"
        print(f"  {icon}  {sc['scenario']:20} DD={sc['max_drawdown_pct']:.1f}%  "
              f"P&L ₹{sc['pnl_inr']:+,.0f}")
    print("=" * 65)
