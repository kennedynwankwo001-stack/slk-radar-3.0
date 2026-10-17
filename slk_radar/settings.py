"""All tunable numbers in one place. Every rule from slk_radar_rules_v1.md maps to a field here."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Settings:
    # --- swings ---
    swing_n: int = 3            # structure swings: 3 candles each side (candle highs/lows)
    av_swing_n: int = 2         # A/V shape swings: 2 closes each side (closes only)
    atr_period: int = 14

    # --- key level zones ---
    touch_atr: float = 0.25     # touch tolerance = 0.25 x ATR of the timeframe
    min_zone_atr: float = 0.10  # minimum zone width (so a thin OCL junction is not paper-thin)
    equal_atr: float = 0.10     # equal highs/lows tolerance
    ocl_min_body_atr: float = 0.50  # both OCL candles need a body of at least this x ATR (my default)
    lookback_daily: int = 120   # Daily candles scanned for levels and history
    h4_lookback: int = 180      # H4 candles scanned for H4 levels
    age_limit: int = 60         # a level older than this (Daily candles) can't start a new DRD
    top_levels: int = 3

    # --- reactions / rejection ---
    history_min_reactions: int = 2
    min_reaction_gap: int = 3   # two reactions must be at least this many candles apart
    strong_margin: float = 0.10  # strong rejection: close beyond the zone edge by > 10% of zone width ...
    strong_margin_atr: float = 0.10  # ... or by > 0.1 x ATR, whichever is larger (my default; thin zones need it)
    wick_bonus: float = 0.50    # wick >= 50% of the candle range = bonus (info only)

    # --- breaks ---
    fake_window: int = 2        # closes back inside within 2 candles = fake breakout
    disrespect_hold: int = 3    # no close back inside for 3 candles = disrespected

    # --- DRD ranking (an internal number only; a DRD alerts when its rejection is strong) ---
    fresh_points: int = 2       # level quality for fresh / tested / history levels
    strong_rejection_points: int = 2
    weak_rejection_points: int = 1
    sweep_points: int = 1
    strong_score: int = 5
    medium_score: int = 3
    use_flips_for_drd: bool = True   # a flipped level is a valid level for a DRD (+2); no separate flip alert in v1
    drd_scan: int = 10          # DRDs are looked for in the last 10 Daily candles (my default)
    tiebreak: str = "candle"     # equal scores: "candle" = the DRD that agrees with the candle colour first, then the closest level (default since the EURAUD test, you had no preference); "closest" = closest level only (your first locked rule); "history" = more reactions first
    early_alert: bool = True     # also send ONE early alert while the Daily candle is still open (flagged "Daily not closed")
    max_alerts_per_day: int = 4  # at most this many NEW bias alerts per Daily candle day (best first: PDH/PDL sweep, external BO, most recent)

    # --- H4 confirmation ---
    h4_swing_mode: str = "close"  # H4 breakout swings are read on the close line, like your line-chart view ("candle" = candle highs/lows with swing_n)
    h4_swing_n: int = 1           # a close is a swing if it is higher/lower than the close on each side
    bo_after_drd_close: bool = True   # H4 breakout must happen after the DRD candle closed
    h4_rejection_window: int = 6      # H4 candles after the breakout
    retest_zone_atr: float = 0.10     # half-width of the "retest of the broken swing" zone

    # --- results ---
    win_rate_goal: float = 0.80
    result_expiry_days: int = 7

    # --- time ---
    daily_close_tz: str = "America/New_York"
    daily_close_hour: int = 17
    display_tz: str = "Africa/Lagos"
