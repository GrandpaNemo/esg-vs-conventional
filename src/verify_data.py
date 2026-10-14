"""
Independent checks on the exported data. Run from the repo root:
    python -m src.verify_data

1. Monthly returns in the Power BI file can be rebuilt from the daily prices.
2. One-day price spikes (bad ticks) are found, and we test whether removing
   them changes ANY monthly return.
3. Each ESG fund's BenchmarkReturn equals its benchmark fund's own return.
4. The risk-free rate (SONIA) looks like UK rates year by year.
5. Calendar-year returns, for comparing with factsheets.
"""
import numpy as np
import pandas as pd

from . import config
from .powerbi_export import PBI_DATA

ok = True


def check(name, passed, detail=""):
    global ok
    ok &= bool(passed)
    print(f"[{'PASS' if passed else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))


daily = pd.read_csv(config.DATA_PROCESSED / "multi_fund_daily_gbp.csv",
                    index_col=0, parse_dates=True)
fact = pd.read_csv(PBI_DATA / "fact_returns_monthly.csv", parse_dates=["Date"])
fund = pd.read_csv(PBI_DATA / "dim_fund.csv").set_index("fund_key")
tick = fund["ticker"]
fact["ticker"] = fact["fund_key"].map(tick)
monthly = fact.pivot(index="Date", columns="ticker", values="Return")


def monthly_from_daily(px):
    return px.resample("ME").last().pct_change(fill_method=None).reindex(monthly.index)


# 1. rebuild monthly returns from daily prices --------------------------------
rebuilt = monthly_from_daily(daily)[monthly.columns]
diff = (rebuilt - monthly).abs().max().max()
check("Monthly returns rebuild exactly from daily prices", diff < 1e-6, f"max diff {diff:.2e}; CSV stores 8 decimals")

# 2. one-day spikes ------------------------------------------------------------
r = daily.pct_change(fill_method=None)
market = r.median(axis=1)
spikes = []
for t in daily.columns:
    s = r[t]
    for i in range(1, len(s) - 1):
        a, b = s.iloc[i], s.iloc[i + 1]
        if (pd.notna(a) and pd.notna(b) and abs(a) > 0.05 and np.sign(a) != np.sign(b)
                and abs((1 + a) * (1 + b) - (1 + market.iloc[i]) * (1 + market.iloc[i + 1])) < 0.05
                and abs(a - market.iloc[i]) > 0.05):
            d = s.index[i]
            px = daily[t].dropna()
            last_in_month = px[px.index.to_period("M") == d.to_period("M")].index.max()
            spikes.append((t, d.date(), round(a, 3), round(b, 3), d == last_in_month))
print(f"\nOne-day spikes found: {len(spikes)}")
for t, d, a, b, me in spikes:
    print(f"   {t:7s} {d}  {a:+.1%} then {b:+.1%}  month-end price? {'YES' if me else 'no'}")
check("No spike falls on a month-end price", not any(s[4] for s in spikes))

clean = daily.copy()
for t, d, *_ in spikes:
    clean.loc[pd.Timestamp(d), t] = np.nan
clean = clean.ffill(limit=1)
diff2 = (monthly_from_daily(clean)[monthly.columns] - monthly).abs().max().max()
check("Removing the spikes changes no monthly return", diff2 < 1e-6, f"max diff {diff2:.2e}")

# 3. benchmark alignment --------------------------------------------------------
esg = fact.dropna(subset=["benchmark_key"]).copy()
own = fact.set_index(["Date", "fund_key"])["Return"]
esg["expected"] = [own.get((d, int(k)), np.nan) for d, k in zip(esg["Date"], esg["benchmark_key"])]
m = esg["BenchmarkReturn"].notna()
check("BenchmarkReturn = benchmark fund's own return, same month",
      np.allclose(esg.loc[m, "BenchmarkReturn"], esg.loc[m, "expected"]),
      f"{int(m.sum())} ESG fund-months checked")
check("Conventional funds have blank BenchmarkReturn",
      fact.loc[fact["benchmark_key"].isna(), "BenchmarkReturn"].isna().all())

# 4. risk-free rate ------------------------------------------------------------
rf = fact.drop_duplicates("Date").set_index("Date")["RF"]
rf_year = ((1 + rf).groupby(rf.index.year).prod() - 1)
print("\nRisk-free (SONIA) compounded per year:", (rf_year * 100).round(2).to_dict())
check("Risk-free between 0% and 6% every year", rf_year.between(-0.001, 0.06).all())

# 5. calendar years (full years only) -------------------------------------------
cal = (1 + monthly).groupby(monthly.index.year).prod() - 1
counts = monthly.notna().groupby(monthly.index.year).sum()
cal = cal.where(counts == 12)
print("\nCalendar-year returns, full years only (blank = partial or not launched):")
print((cal * 100).round(1).to_string(na_rep="-"))

print("\nALL CHECKS PASSED" if ok else "\nSOME CHECKS FAILED - paste this output to Claude")
