"""
Turn raw downloads into clean, comparable return series.

The order matters:
  1. put each price in major currency units (pence -> pounds)
  2. repair obvious unit glitches (a single day quoted in pounds instead of pence)
  3. convert everything to GBP
  4. align the two funds on one calendar and patch short gaps
  5. take month-end prices -> monthly returns
  6. build the matching monthly risk-free rate
Every step records what it changed in a QualityLog so the README can say
exactly what was done to the data.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import config


@dataclass
class QualityLog:
    """Collects notes on every cleaning decision, for a data-quality report."""
    notes: list[str] = field(default_factory=list)

    def add(self, msg: str) -> None:
        self.notes.append(msg)

    def __str__(self) -> str:
        return "\n".join(f"- {n}" for n in self.notes) or "- no issues found"


# --------------------------------------------------------------------------
# 1-2. Units
# --------------------------------------------------------------------------
def to_major_units(s: pd.Series, currency: str) -> tuple[pd.Series, str]:
    """GBp / GBX (pence) -> GBP (pounds). Other currencies pass through."""
    if currency in ("GBp", "GBX", "GBx"):
        return s / 100.0, "GBP"
    return s, currency


def fix_unit_glitches(s: pd.Series, log: QualityLog,
                      ratio: float = config.PENCE_RATIO_FLAG) -> pd.Series:
    """Repair isolated days where Yahoo mixes pounds and pence.

    LSE data on Yahoo sometimes has single days 100x too big or too small.
    We compare each price with a centred 11-day rolling median: anything more
    than `ratio` times away is rescaled by 100 in the right direction.
    """
    s = s.copy()
    med = s.rolling(11, center=True, min_periods=3).median()
    rel = s / med
    too_big, too_small = rel > ratio, rel < 1 / ratio
    s[too_big] /= 100
    s[too_small] *= 100
    n = int(too_big.sum() + too_small.sum())
    if n:
        log.add(f"{s.name}: rescaled {n} day(s) with a pounds/pence glitch "
                f"({', '.join(d.strftime('%Y-%m-%d') for d in s.index[too_big | too_small][:5])}"
                f"{'...' if n > 5 else ''})")
    return s


# --------------------------------------------------------------------------
# 3. Currency
# --------------------------------------------------------------------------
def convert_to_gbp(price: pd.Series, fx_to_gbp: pd.Series, log: QualityLog) -> pd.Series:
    """Multiply a foreign-currency price by (GBP per 1 unit of that currency).

    The FX series is forward-filled onto the price dates (FX trades on days
    the LSE is shut, and vice versa). The SRI fund is unhedged, so this gives
    the GBP value of the same holding: exactly what a UK investor experiences.
    """
    fx = fx_to_gbp.reindex(price.index.union(fx_to_gbp.index)).sort_index()
    fx = fx.ffill(limit=config.MAX_FFILL_DAYS).reindex(price.index)
    missing = int(fx[price.notna()].isna().sum())
    if missing:
        log.add(f"{price.name}: {missing} day(s) with no FX rate available; left as NaN")
    out = price * fx
    out.name = price.name
    return out


# --------------------------------------------------------------------------
# 4. Alignment
# --------------------------------------------------------------------------
def align_prices(prices: pd.DataFrame, log: QualityLog) -> pd.DataFrame:
    """Put both funds on one trading calendar with no gaps.

    * start from the first day on which EVERY fund has a price
    * forward-fill gaps of up to MAX_FFILL_DAYS (a missing quote on a quiet day)
    * report longer gaps rather than silently filling them
    * drop weekends, and days where the whole row is missing
    """
    p = prices.copy()
    p = p[p.index.dayofweek < 5]
    first_common = p.dropna().index.min()
    p = p.loc[first_common:]
    p = p.dropna(how="all")

    for col in p.columns:
        isna = p[col].isna()
        # length of each run of consecutive NaNs
        runs = isna.groupby((~isna).cumsum()).sum()
        long_gaps = int((runs > config.MAX_FFILL_DAYS).sum())
        if isna.any():
            log.add(f"{col}: {int(isna.sum())} missing day(s) after alignment, "
                    f"longest gap {int(runs.max())} day(s)"
                    + (f"; {long_gaps} gap(s) too long to fill" if long_gaps else ""))

    p = p.ffill(limit=config.MAX_FFILL_DAYS)
    log.add(f"Aligned sample: {p.index.min():%Y-%m-%d} to {p.index.max():%Y-%m-%d}, "
            f"{len(p)} trading days")
    return p


def flag_large_moves(prices: pd.DataFrame, log: QualityLog,
                     threshold: float = config.DAILY_MOVE_FLAG) -> pd.DataFrame:
    """List daily moves above `threshold` so you can eyeball them.

    These are NOT deleted: March 2020 had genuine moves of this size. The
    test is whether BOTH funds moved together (real market news) or only
    one did (more likely a bad tick).
    """
    r = prices.pct_change(fill_method=None)
    big = r[(r.abs() > threshold).any(axis=1)]
    if len(big):
        log.add(f"{len(big)} day(s) with a move above {threshold:.0%} in at least one "
                f"fund; see large_moves.csv and check that both funds moved together")
    return big


# --------------------------------------------------------------------------
# 5. Monthly returns
# --------------------------------------------------------------------------
def last_complete_month_end(today: pd.Timestamp | None = None) -> pd.Timestamp:
    """Month-end date of the previous calendar month (the latest finished one)."""
    today = pd.Timestamp.today() if today is None else pd.Timestamp(today)
    return today.to_period("M").start_time.normalize() - pd.Timedelta(days=1)


def monthly_returns(daily_prices: pd.DataFrame,
                    end: pd.Timestamp | None = None) -> pd.DataFrame:
    """Simple monthly returns from the last price in each calendar month.

    The first month in the sample is used only as the starting price, and any
    month that is not yet finished is dropped.
    """
    end = last_complete_month_end() if end is None else pd.Timestamp(end)
    month_end = daily_prices.resample("ME").last()
    month_end = month_end.loc[:end]
    rets = month_end.pct_change(fill_method=None).iloc[1:]
    return rets


# --------------------------------------------------------------------------
# 6. Risk-free rate
# --------------------------------------------------------------------------
def monthly_rf_from_sonia(sonia_pct: pd.Series) -> pd.Series:
    """Compound daily SONIA into a monthly return.

    SONIA is quoted as an annualised % on an ACT/365 basis, and the rate set
    on a Friday applies over the weekend. So we spread it over calendar days,
    carry each fixing forward until the next one, and compound:
        monthly rf = prod(1 + SONIA/100/365) - 1
    """
    daily = sonia_pct.sort_index()
    # the last fixing applies until the next business day (a Friday rate
    # covers Saturday and Sunday), so the covered period runs to the day before
    last_covered = daily.index.max() + pd.offsets.BDay(1) - pd.Timedelta(days=1)
    cal = pd.date_range(daily.index.min(), last_covered, freq="D")
    daily = daily.reindex(cal).ffill()
    growth = (1 + daily / 100 / 365).resample("ME").prod() - 1
    # drop a first/last month that is only partly covered
    first_full = daily.index.min() + pd.offsets.MonthEnd(0) \
        if daily.index.min().day == 1 else daily.index.min() + pd.offsets.MonthEnd(1)
    growth = growth.loc[first_full:]
    if last_covered != last_covered + pd.offsets.MonthEnd(0):
        growth = growth.iloc[:-1]
    growth.name = "RF"
    return growth


def gbp_to_usd_returns(r_gbp: pd.DataFrame, gbpusd_daily: pd.Series) -> pd.DataFrame:
    """Convert monthly GBP returns into USD returns: (1+r_gbp)(1+r_fx) - 1.

    Needed in step 5: Fama-French developed factors are USD returns, so the
    regression is run in USD to keep the left- and right-hand sides consistent.
    """
    fx_m = gbpusd_daily.resample("ME").last().pct_change(fill_method=None)
    fx_m = fx_m.reindex(r_gbp.index)
    return (1 + r_gbp).mul(1 + fx_m, axis=0) - 1
