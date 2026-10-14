"""
Project configuration: tickers, dates, fees and file locations.

Everything that you might want to change (a different fund pair, a different
start date) lives here, so the rest of the code never hard-codes it.
"""
from pathlib import Path

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
DATA_RAW = ROOT / "data" / "raw"
DATA_PROCESSED = ROOT / "data" / "processed"
FIGURES = ROOT / "figures"

# --------------------------------------------------------------------------
# The fund pair
# --------------------------------------------------------------------------
# Verified against iShares factsheets (Oct 2026):
#   * SUSW.L is the EUR (Acc) share class, IE00BYX2JD69. It is listed on the
#     LSE but QUOTED IN EUR, so it must be converted to GBP before comparing.
#     (The GBP-quoted lines of this fund, SUWG and SGWS, are distributing, and
#     SGWS is also currency-hedged, so neither is a like-for-like comparator.)
#   * SWDA.L is the USD (Acc) share class, IE00B4L5Y983, quoted in GBP pence.
# Both are accumulating, so dividends are reinvested inside the price.
#
# quote_currency is what we EXPECT Yahoo to report. The loader checks the
# live value and warns if it differs.
#
# TER: check the latest factsheet / KIID and fill in before reporting.
FUNDS = {
    "SRI": {
        "ticker": "SUSW.L",
        "name": "iShares MSCI World SRI UCITS ETF EUR (Acc)",
        "isin": "IE00BYX2JD69",
        "index": "MSCI World SRI Select Reduced Fossil Fuel",
        "quote_currency": "EUR",
        "ter": None,  # TODO: fill in from the current factsheet
        "listing_date": "2017-10-16",
    },
    "CONV": {
        "ticker": "SWDA.L",
        "name": "iShares Core MSCI World UCITS ETF USD (Acc)",
        "isin": "IE00B4L5Y983",
        "index": "MSCI World",
        "quote_currency": "GBp",  # pence
        "ter": 0.0020,
        "listing_date": "2009-09-28",
    },
}

# FX rates from Yahoo. "EURGBP=X" = pounds per 1 euro.
FX_TICKERS = {
    "EURGBP": "EURGBP=X",  # to convert the SRI fund's EUR price into GBP
    "GBPUSD": "GBPUSD=X",  # for the factor regression later (factors are in USD)
}

# --------------------------------------------------------------------------
# Sample period
# --------------------------------------------------------------------------
# Start at the later fund's LSE listing. The first full month of returns is
# therefore November 2017 (October month-end price -> November month-end).
START_DATE = FUNDS["SRI"]["listing_date"]
END_DATE = None  # None = up to the last COMPLETE calendar month

# --------------------------------------------------------------------------
# External data sources
# --------------------------------------------------------------------------
# Bank of England SONIA (series IUDSOIA), annualised %, daily.
BOE_SONIA_URL = (
    "https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp"
    "?csv.x=yes&Datefrom=01/Jan/2017&Dateto=now&SeriesCodes=IUDSOIA"
    "&CSVF=TN&UsingCodes=Y&VPD=Y&VFD=N"
)
# FRED mirror of the same series, used if the BoE request fails.
FRED_SONIA_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=IUDSOIA"

# Kenneth French Data Library: Developed-markets factors (USD, monthly, %).
FF_BASE = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
FF_DEV_5F_ZIP = FF_BASE + "Developed_5_Factors_CSV.zip"
FF_DEV_MOM_ZIP = FF_BASE + "Developed_Mom_Factor_CSV.zip"

# --------------------------------------------------------------------------
# Cleaning thresholds
# --------------------------------------------------------------------------
MAX_FFILL_DAYS = 5          # longest gap we patch by carrying the last price
DAILY_MOVE_FLAG = 0.08      # flag (not delete) daily moves bigger than 8%
PENCE_RATIO_FLAG = 50       # a price 50x away from its neighbours = units glitch

# --------------------------------------------------------------------------
# Market regimes (used in step 4)
# --------------------------------------------------------------------------
REGIMES = {
    "COVID crash": ("2020-02-01", "2020-04-30"),
    "Recovery": ("2020-05-01", "2021-12-31"),
    "Energy & inflation shock": ("2022-01-01", "2022-12-31"),
    "2023 onwards": ("2023-01-01", None),
}
# Note for the write-up: the SRI index rules were reportedly changed in May 2024
# to cap sector weights at +/-1% of MSCI World (verify on MSCI's methodology
# page before citing). If so, sector tilts should shrink after mid-2024, and a
# pre/post split is a useful extra regime.
SRI_METHODOLOGY_CHANGE = "2024-06-01"
