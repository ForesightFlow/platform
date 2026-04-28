"""Exponential hazard model: S(τ) = exp(-λτ), λ̂ = 1/mean(τ).

Used for deadline_resolved YES markets to characterize how quickly
the underlying event occurs after market opening (paper §7.2).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import stats


@dataclass
class HazardFit:
    category: str
    n: int
    lambda_mle: float     # events/day
    half_life_days: float  # ln(2) / lambda
    mean_tau_days: float
    ks_statistic: float
    ks_pvalue: float
    tau_p25: float
    tau_p50: float
    tau_p75: float


def fit_exponential(category: str, tau_days: list[float]) -> HazardFit:
    """MLE fit for exponential distribution: λ̂ = 1/mean(τ).

    KS goodness-of-fit tests whether exponential is a reasonable model.
    pvalue < 0.05 → reject exponential; treat λ as approximate only.
    """
    arr = np.array(tau_days, dtype=float)
    lam = 1.0 / arr.mean()
    ks_stat, ks_pval = stats.kstest(arr, "expon", args=(0.0, 1.0 / lam))
    return HazardFit(
        category=category,
        n=len(arr),
        lambda_mle=lam,
        half_life_days=math.log(2) / lam,
        mean_tau_days=float(arr.mean()),
        ks_statistic=float(ks_stat),
        ks_pvalue=float(ks_pval),
        tau_p25=float(np.percentile(arr, 25)),
        tau_p50=float(np.percentile(arr, 50)),
        tau_p75=float(np.percentile(arr, 75)),
    )
