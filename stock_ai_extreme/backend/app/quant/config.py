"""
Phase 21 — quantitative analytics configuration.

Every threshold, minimum sample size and default is here so nothing is a hidden
constant. The same numbers the engines validate against are the ones
`GET /api/quant/config` publishes.
"""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class QuantSettings(BaseSettings):
    # --- sample-size floors (below these, an answer is None plus a reason) ---
    #: Absolute minimum observations for any distributional statement.
    quant_min_observations: int = Field(default=30, ge=10, le=500)
    #: Minimum observations for a regression (alpha + beta + HAC lags).
    quant_min_regression_observations: int = Field(default=60, ge=20, le=2000)
    #: Minimum observations for ADF/KPSS to be worth reporting.
    quant_min_stationarity_observations: int = Field(default=40, ge=20, le=2000)
    #: Minimum events for an event-study significance test (fewer = anecdote).
    quant_min_event_study_sample: int = Field(default=5, ge=2, le=200)

    # --- hypothesis testing ---
    #: Conventional significance level; reported alongside every p-value so the
    #: reader can apply their own threshold instead.
    quant_significance_level: float = Field(default=0.05, gt=0.0, lt=0.5)
    #: ADF/KPSS regression lag selection: "aic" | "bic" | "t-stat" | fixed int.
    quant_adf_autolag: str = Field(default="aic", pattern="^(aic|bic|t-stat|none)$")
    quant_max_lags: int = Field(default=20, ge=1, le=100)

    # --- Newey-West HAC ---
    #: Bartlett kernel bandwidth. `None` (the default) uses the Newey-West rule
    #: floor(4*(T/100)^(2/9)); a fixed value is accepted for reproducibility.
    quant_hac_maxlags: int | None = Field(default=None, ge=1, le=200)

    # --- variance ratio / Hurst ---
    #: Holding periods tested by the Lo-MacKinlay variance-ratio test.
    quant_variance_ratio_periods: str = "2,4,8,16"
    #: Rescaled-range window sizes for the Hurst exponent.
    quant_hurst_windows: str = "8,16,32,64,128"
    #: VR/Hurst decision bands (documented, not magic).
    quant_trending_threshold: float = Field(default=1.15, gt=1.0, le=3.0)
    quant_mean_reverting_threshold: float = Field(default=0.85, gt=0.0, lt=1.0)

    # --- risk ---
    #: Confidence levels reported by the tail-risk block.
    quant_var_confidence_levels: str = "0.90,0.95,0.99"
    #: Cornish-Fisher is only reported when the sample can support the 3rd and
    #: 4th moments (skew/kurtosis are very noisy below ~60 observations).
    quant_min_observations_for_cornish_fisher: int = Field(default=60, ge=30, le=2000)
    #: EWMA decay for the volatility readout (RiskMetrics' 0.94 is the industry
    #: default and is what is reported unless overridden).
    quant_ewma_lambda: float = Field(default=0.94, gt=0.0, lt=1.0)

    # --- event study ---
    #: Estimation-window length (bars) used to fit the market model per event.
    quant_event_estimation_window: int = Field(default=120, ge=20, le=600)
    #: Bars between the estimation window and the event (avoids leakage).
    quant_event_gap_window: int = Field(default=10, ge=0, le=60)
    #: Event window offsets (bars) reported as CAR.
    quant_event_window: str = "-5,0,5,20"
    #: Bootstrap resamples for the cross-sectional mean CI.
    quant_bootstrap_resamples: int = Field(default=5000, ge=500, le=50000)
    quant_bootstrap_seed: int = 20260101

    # --- HTTP defaults ---
    quant_default_lookback_days: int = Field(default=365, ge=60, le=3650)
    quant_max_tickers: int = Field(default=25, ge=1, le=100)

    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @property
    def variance_ratio_periods(self) -> list[int]:
        return [int(x) for x in self.quant_variance_ratio_periods.split(",") if x.strip()]

    @property
    def hurst_window_list(self) -> list[int]:
        return [int(x) for x in self.quant_hurst_windows.split(",") if x.strip()]

    @property
    def confidence_levels(self) -> list[float]:
        return [float(x) for x in self.quant_var_confidence_levels.split(",") if x.strip()]

    @property
    def event_window_offsets(self) -> list[int]:
        return [int(x) for x in self.quant_event_window.split(",") if x.strip()]


quant_settings = QuantSettings()
