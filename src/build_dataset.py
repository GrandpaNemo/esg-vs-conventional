"""
Step 1 of the project: download everything and build the clean dataset.

Run from the repo root:
    python -m src.build_dataset            # uses cached raw files if present
    python -m src.build_dataset --refresh  # re-download everything

Outputs in data/processed/:
    daily_prices_gbp.csv   both funds in GBP, aligned, gaps patched
    monthly_returns.csv    SRI, CONV, RF and excess returns (GBP, decimals)
    monthly_returns_usd.csv  fund returns in USD (for the factor regression)
    ff_factors.csv         Fama-French developed 5 factors + momentum, sample period
    large_moves.csv        daily moves above the flag threshold, to eyeball
    data_quality.md        every cleaning decision, for the README
"""
from __future__ import annotations

import argparse

import pandas as pd

from . import cleaning, config, data_loader


def build(refresh: bool = False, verbose: bool = True) -> dict[str, pd.DataFrame]:
    log = cleaning.QualityLog()

    # ---- 1. Download ---------------------------------------------------
    raw_prices, currencies = data_loader.download_fund_prices(refresh)
    fx = data_loader.download_fx(refresh)
    sonia = data_loader.download_sonia(refresh)
    factors = data_loader.download_ff_factors(refresh)

    # ---- 2. Units, glitches, currency ----------------------------------
    gbp = {}
    for label, fund in config.FUNDS.items():
        t = fund["ticker"]
        s = raw_prices[t].dropna().rename(label)
        s, ccy = cleaning.to_major_units(s, currencies[t])
        s = cleaning.fix_unit_glitches(s, log)
        if ccy == "EUR":
            s = cleaning.convert_to_gbp(s, fx["EURGBP"], log)
            log.add(f"{label} ({t}) is quoted in EUR; converted to GBP with daily EURGBP")
        elif ccy == "USD":
            s = cleaning.convert_to_gbp(s, 1 / fx["GBPUSD"], log)
            log.add(f"{label} ({t}) is quoted in USD; converted to GBP with daily GBPUSD")
        elif ccy != "GBP":
            raise ValueError(f"No conversion rule for {t} in {ccy}")
        gbp[label] = s

    # ---- 3. Align and check --------------------------------------------
    daily = cleaning.align_prices(pd.DataFrame(gbp), log)
    large = cleaning.flag_large_moves(daily, log)

    # ---- 4. Monthly returns + risk-free ---------------------------------
    rets = cleaning.monthly_returns(daily)
    rf = cleaning.monthly_rf_from_sonia(sonia)
    monthly = rets.join(rf, how="left")
    if monthly["RF"].isna().any():
        n = int(monthly["RF"].isna().sum())
        log.add(f"RF missing for {n} month(s) at the end of the sample "
                f"(SONIA not yet published); those months are dropped")
        monthly = monthly.dropna(subset=["RF"])
    for label in config.FUNDS:
        monthly[f"{label}_excess"] = monthly[label] - monthly["RF"]
    monthly["SRI_minus_CONV"] = monthly["SRI"] - monthly["CONV"]
    log.add(f"Monthly sample: {monthly.index.min():%b %Y} to {monthly.index.max():%b %Y}, "
            f"{len(monthly)} months")

    usd = cleaning.gbp_to_usd_returns(monthly[list(config.FUNDS)], fx["GBPUSD"])
    ff = factors.loc[monthly.index.min():monthly.index.max()]
    if len(ff) < len(monthly):
        log.add(f"Fama-French factors end {ff.index.max():%b %Y}; the regression will "
                f"use {len(ff)} of {len(monthly)} months (the library updates with a lag)")

    # ---- 5. Save ---------------------------------------------------------
    out = config.DATA_PROCESSED
    out.mkdir(parents=True, exist_ok=True)
    daily.to_csv(out / "daily_prices_gbp.csv")
    monthly.to_csv(out / "monthly_returns.csv")
    usd.to_csv(out / "monthly_returns_usd.csv")
    ff.to_csv(out / "ff_factors.csv")
    large.to_csv(out / "large_moves.csv")

    fees = "\n".join(
        f"- {k}: {f['name']} ({f['isin']}), TER "
        + (f"{f['ter']:.2%}" if f["ter"] is not None else "TO FILL IN")
        for k, f in config.FUNDS.items())
    (out / "data_quality.md").write_text(
        "# Data quality report\n\n## Funds\n" + fees +
        "\n\n## Cleaning log\n" + str(log) + "\n")

    if verbose:
        print("\nCleaning log\n" + str(log))
        print("\nFirst rows of monthly_returns.csv")
        print(monthly.head().round(4))
    return {"daily": daily, "monthly": monthly, "monthly_usd": usd,
            "factors": ff, "large_moves": large, "log": log}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="re-download all raw data")
    build(refresh=ap.parse_args().refresh)
