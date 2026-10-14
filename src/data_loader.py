"""
Download raw data and cache it in data/raw/.

Each function saves what it downloads, so re-running the notebook does not hit
the internet again unless you pass refresh=True. Raw files are saved exactly
as received; all cleaning happens in cleaning.py.
"""
from __future__ import annotations

import io
import warnings
import zipfile

import pandas as pd
import requests

from . import config

HEADERS = {"User-Agent": "Mozilla/5.0 (research project; pandas)"}


# --------------------------------------------------------------------------
# Yahoo Finance: fund prices and FX
# --------------------------------------------------------------------------
def download_yahoo(tickers: list[str], start: str, end: str | None = None,
                   name: str = "prices", refresh: bool = False) -> pd.DataFrame:
    """Daily close prices for a list of Yahoo tickers (one column each).

    auto_adjust=True makes 'Close' the dividend- and split-adjusted price.
    For accumulating ETFs this barely changes anything, but it protects us if
    a distributing fund is ever swapped in.
    """
    path = config.DATA_RAW / f"{name}.csv"
    if path.exists() and not refresh:
        return pd.read_csv(path, index_col=0, parse_dates=True)

    import yfinance as yf

    raw = yf.download(tickers, start=start, end=end, auto_adjust=True,
                      progress=False, group_by="column", threads=False)
    if raw.empty:
        raise RuntimeError(f"Yahoo returned no data for {tickers}")

    close = raw["Close"]
    if isinstance(close, pd.Series):  # single ticker
        close = close.to_frame(tickers[0])
    close = close[tickers]  # keep the requested order
    close.index = pd.to_datetime(close.index).tz_localize(None)
    close.index.name = "date"

    config.DATA_RAW.mkdir(parents=True, exist_ok=True)
    close.to_csv(path)
    return close


def yahoo_currencies(tickers: list[str]) -> dict[str, str | None]:
    """The quote currency Yahoo reports for each ticker (e.g. 'GBp', 'EUR').

    Used to double-check the currency assumptions in config.py. Returns None
    for a ticker if the lookup fails, and the caller falls back to config.
    """
    import yfinance as yf

    out = {}
    for t in tickers:
        try:
            out[t] = yf.Ticker(t).fast_info["currency"]
        except Exception:  # metadata endpoints are flaky; never fatal
            out[t] = None
    return out


def download_fund_prices(refresh: bool = False) -> tuple[pd.DataFrame, dict]:
    """Prices for both funds plus the currency each is quoted in."""
    tickers = [f["ticker"] for f in config.FUNDS.values()]
    prices = download_yahoo(tickers, config.START_DATE, config.END_DATE,
                            name="fund_prices_raw", refresh=refresh)

    live = yahoo_currencies(tickers)
    currencies = {}
    for f in config.FUNDS.values():
        t, expected = f["ticker"], f["quote_currency"]
        got = live.get(t)
        if got is not None and got != expected:
            warnings.warn(f"{t}: Yahoo says currency={got!r}, config expects "
                          f"{expected!r}. Using Yahoo's value; check config.py.")
        currencies[t] = got or expected
    return prices, currencies


def download_fx(refresh: bool = False) -> pd.DataFrame:
    """Daily FX rates, columns named EURGBP, GBPUSD."""
    tickers = list(config.FX_TICKERS.values())
    fx = download_yahoo(tickers, "2017-01-01", config.END_DATE,
                        name="fx_raw", refresh=refresh)
    return fx.rename(columns={v: k for k, v in config.FX_TICKERS.items()})


# --------------------------------------------------------------------------
# Risk-free rate: SONIA
# --------------------------------------------------------------------------
def _read_two_column_csv(text: str, value_name: str) -> pd.Series:
    """Parse a 'date, value' CSV whatever the header names and date format."""
    df = pd.read_csv(io.StringIO(text))
    df.columns = ["date", value_name]
    df["date"] = pd.to_datetime(df["date"], dayfirst=True, format="mixed")
    df[value_name] = pd.to_numeric(df[value_name], errors="coerce")  # '.' = missing on FRED
    return df.dropna().set_index("date")[value_name].sort_index()


def download_sonia(refresh: bool = False) -> pd.Series:
    """Daily SONIA, annualised percent. Tries the BoE first, then FRED."""
    path = config.DATA_RAW / "sonia_raw.csv"
    if path.exists() and not refresh:
        return pd.read_csv(path, index_col=0, parse_dates=True).squeeze("columns")

    errors = []
    for source, url in [("BoE", config.BOE_SONIA_URL), ("FRED", config.FRED_SONIA_URL)]:
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            r.raise_for_status()
            sonia = _read_two_column_csv(r.text, "SONIA")
            if len(sonia) < 100:
                raise ValueError(f"only {len(sonia)} rows - probably an error page")
            sonia.attrs["source"] = source
            config.DATA_RAW.mkdir(parents=True, exist_ok=True)
            sonia.to_csv(path)
            print(f"SONIA downloaded from {source}: {len(sonia)} days")
            return sonia
        except Exception as e:
            errors.append(f"{source}: {e}")
    raise RuntimeError("Could not download SONIA.\n" + "\n".join(errors))


# --------------------------------------------------------------------------
# Fama-French factors
# --------------------------------------------------------------------------
def parse_french_csv(text: str) -> pd.DataFrame:
    """Parse the MONTHLY table from a Kenneth French CSV.

    These files start with a few description lines, then a header row that
    begins with a comma, then rows like '199007,  0.86, ...', then a blank
    line, then an annual table we ignore. Values are in percent; we return
    decimals with a month-end DatetimeIndex.
    """
    lines = text.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.strip().startswith(","))
    header = [c.strip() for c in lines[start].split(",")]
    header[0] = "yyyymm"

    rows = []
    for ln in lines[start + 1:]:
        parts = [p.strip() for p in ln.split(",")]
        if not parts[0].isdigit() or len(parts[0]) != 6:
            break  # end of the monthly table
        rows.append(parts)

    df = pd.DataFrame(rows, columns=header)
    df.index = pd.to_datetime(df.pop("yyyymm"), format="%Y%m") + pd.offsets.MonthEnd(0)
    df.index.name = "date"
    df = df.apply(pd.to_numeric) / 100.0
    df[df <= -99.99 / 100] = float("nan")  # French uses -99.99 for missing
    return df


def _download_french_zip(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        return z.read(name).decode("latin-1")


def download_ff_factors(refresh: bool = False) -> pd.DataFrame:
    """Developed-markets FF5 + momentum, monthly, decimals, in USD.

    Columns: Mkt-RF, SMB, HML, RMW, CMA, RF, WML.
    """
    path = config.DATA_RAW / "ff_developed_factors.csv"
    if path.exists() and not refresh:
        return pd.read_csv(path, index_col=0, parse_dates=True)

    f5 = parse_french_csv(_download_french_zip(config.FF_DEV_5F_ZIP))
    mom = parse_french_csv(_download_french_zip(config.FF_DEV_MOM_ZIP))
    mom.columns = ["WML"]
    factors = f5.join(mom, how="inner")

    config.DATA_RAW.mkdir(parents=True, exist_ok=True)
    factors.to_csv(path)
    return factors
