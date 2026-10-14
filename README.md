# Does investing ethically cost you returns?

**A Power BI dashboard comparing 5 ESG funds with their conventional equivalents, in GBP, from 2017.**

> Status: data pipeline and DAX measures complete. Dashboard in progress.
> *Historical analysis only. Not investment advice.*

<!-- Add: hero screenshot of page 1, then the one-sentence answer once you have it -->

## The question
Have sustainable (ESG/SRI) equity funds delivered materially different risk-adjusted returns from conventional funds that cover the same market? If so, when, and why: sector tilts, or particular market regimes such as the 2022 energy shock?

## Funds compared

| ESG fund | Ticker | Conventional benchmark | Ticker |
|---|---|---|---|
| iShares MSCI World SRI | SUSW.L | iShares Core MSCI World | SWDA.L |
| iShares MSCI World CTB Enhanced ESG | EGMW.L | iShares Core MSCI World | SWDA.L |
| Xtrackers MSCI World ESG | XZW0.L | iShares Core MSCI World | SWDA.L |
| Vanguard ESG Global All Cap | V3AB.L | Vanguard FTSE All-World | VWRP.L |
| iShares MSCI USA SRI | SUUS.L | iShares Core S&P 500 | CSP1.L |

All are accumulating share classes, so dividends are reinvested. Lines quoted in EUR or USD are converted to GBP with daily FX, the return a UK investor actually gets. The fund list lives in `config/funds.csv`; add a row to add a fund.

## How it's built

```
Yahoo Finance prices ─┐
BoE SONIA (risk-free) ─┼─► Python: clean, convert to GBP, ─► star-schema CSVs ─► Power BI
Daily FX ─────────────┘   monthly returns, benchmarks        (powerbi/data/)      model + DAX
```

**Data model:** `fact_returns_monthly` (one row per fund per month: return, risk-free, excess, benchmark and active return), joined to `dim_fund`, `dim_date` (with market regime) and `fact_sector_weights`.

**DAX measures** (`powerbi/measures.dax`, 34 measures): CAGR, volatility, Sharpe, Sortino, max drawdown, growth of £10k, tracking error, information ratio, beta, win rate, rolling 12-month return gap and rolling 36-month Sharpe, regime returns and sector tilts. Every measure is cross-checked against an independent, unit-tested Python implementation (`metrics_check.csv`).

**Fair comparison by design:** each ESG fund's row carries its benchmark's return for the same month, so ESG-vs-benchmark comparisons always cover identical periods, whatever the fund's launch date.

## Reproduce

```bash
pip install -r requirements.txt
pytest -q
python -m src.powerbi_export
```
This writes `powerbi/data/ESG_funds_model.xlsx` (one named table per sheet) for the Power BI web service. Then follow `powerbi/BUILD_GUIDE.md`.

## Repo structure
```
config/funds.csv          the fund universe and benchmark pairs
src/                      download, cleaning, export (Python)
tests/                    offline unit tests
powerbi/measures.dax      all DAX measures
powerbi/theme_esg.json    report theme
powerbi/BUILD_GUIDE.md    step-by-step build
powerbi/data/             generated CSVs for Power BI
notebooks/                exploratory analysis (two-fund deep dive)
```

## Limitations
- Short history: under 9 years for most pairs, and about 5 for the Vanguard pair. Differences may be noise.
- Market prices, not NAV. Small premium/discount effects are possible.
- Sector weights are current snapshots, not history.
- The USA SRI fund is compared with the S&P 500, a close but not identical parent index.
