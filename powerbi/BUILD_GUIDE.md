# Power BI build guide (web version, app.powerbi.com)

Follow in order. Each stage ends with a check, so mistakes surface early rather than on the last page.

**You need:** Python 3.10+, and a Power BI sign-in with a **work or school account** (your university account). The web version runs on Mac or Windows.

---

## Stage 0 — Generate the data (20 min)

```bash
pip install -r requirements.txt
pytest -q                          # 20 offline tests should pass
python -m src.powerbi_export       # downloads, cleans, writes powerbi/data/
```

It prints a cleaning log and a metrics table. **Keep that output**: those numbers are the answer key for your DAX.

Check:
- [ ] Every ticker shows a date range in the log. If one says `NO DATA`, fix its ticker in `config/funds.csv` and re-run.
- [ ] Read `powerbi/data/data_quality.md`.
- [ ] Calendar-year returns roughly match each fund's factsheet (within ~1 percentage point).

**Fill in the sector weights now, before uploading.** Open `powerbi/data/fact_sector_weights.csv` and type each fund's sector weights from its factsheet, as decimals (0.235, not 23.5), with `AsOf` = the factsheet date. Do at least SWDA, SUSW, VWRP and V3AB. Then run `python -m src.powerbi_export` again. It never overwrites your typed weights, and it rebuilds the workbook.

The file you upload is **`powerbi/data/ESG_funds_model.xlsx`**. It has one sheet per table, each formatted as a named Excel table.

## Stage 1 — Check you can edit models on the web (10 min)

Editing a model in the browser (adding relationships and DAX) needs three things:
1. Your organisation's admin has left **"Users can edit data models in the Power BI service"** switched on.
2. You have write permission on the model. You do if you created it.
3. A suitable workspace. This works in Pro workspaces, and may not work in **My workspace**.

Quick test: do Stage 2 step 1, open the semantic model, and look for an **Open data model** / **Edit** button.
- **It works** → carry on.
- **It's greyed out, or you can't create a workspace** → start a free Power BI **Pro trial** if your account is offered one (the prompt usually appears when you click *New workspace*). Create a workspace called `ESG Funds` and import there. If the trial is blocked, ask University IT whether students have Power BI Pro.

## Stage 2 — Load and model (45 min)

1. **Upload `ESG_funds_model.xlsx` to your university OneDrive first**, then in Power BI: workspace → **New item → Semantic model → Excel** → pick the file from OneDrive. (A workbook uploaded from your laptop can't be refreshed later; one on OneDrive can.) Don't use any old "Create → paste/CSV" route: Microsoft has retired it.
2. Open the semantic model → **Open data model**, and switch to **Editing**.
3. **Check data types** (select a column → Properties pane):
   - `Date`, `FirstMonth`, `LastMonth` → **Date**
   - `Return`, `RF`, `ExcessReturn`, `BenchmarkReturn`, `ActiveReturn`, `ter`, `Weight` → **Decimal number**
   - `fund_key`, `benchmark_key`, `in_pair_period`, `in_common_period` → **Whole number**
   - `BenchmarkReturn` must be **empty (null) for the 3 conventional funds**, not 0. This matters: the benchmark measures rely on blanks.
4. **Relationships** (Manage relationships; delete any it auto-detected, then create these, all *many-to-one, single direction*):
   - `fact_returns_monthly[fund_key]` → `dim_fund[fund_key]`
   - `fact_returns_monthly[Date]` → `dim_date[Date]`
   - `fact_sector_weights[fund_key]` → `dim_fund[fund_key]`
   - `dim_date[Regime]` → `dim_regime[Regime]` (optional)
   - There must be **no** relationship on `benchmark_key`.
5. Hide key and flag columns from report view (Properties → *Is hidden*), so the field list stays clean.

Regime names are numbered ("1. Pre-COVID" … "5. 2023 onwards"), so they sort correctly without any extra setup.

Check: the diagram is a star, with `fact_returns_monthly` in the middle. **Screenshot it** for the README; recruiters look for this.

## Stage 3 — Measures (1–1.5 h)

1. Select the table `fact_returns_monthly` → **New measure**. Paste one block at a time from `measures.dax` (34 measures). Optional tidy-up: **New table** → `_Measures = ROW ( "x", 1 )`, create the measures there instead, and hide column `x`.
2. Formatting (Properties pane):
   - Returns, CAGR, volatility, drawdowns, gaps, tracking error, win rate → **Percentage, 1 dp**
   - Sharpe, Sortino, Information Ratio, Beta, Correlation → **Decimal, 2 dp**
   - Growth measures → **Currency £, 0 dp**
3. **Validate against Python** (this is the important part):
   - Create a report from the model. Add a table visual: rows `dim_fund[short_name]`. Values: `Month Count`, `CAGR`, `Ann. Volatility`, `Sharpe Ratio`, `Max Drawdown`, `Benchmark CAGR`, `CAGR Gap vs Benchmark`, `Benchmark Sharpe Ratio`, `Tracking Error`, `Beta vs Benchmark`.
   - Visual-level filter: `in_pair_period` is 1. No date slicer.
   - Compare with `metrics_check.csv` / the Stage 0 output. Every number should match. If one doesn't, the DAX is wrong, not Python, because the Python version is unit-tested.

Check: [ ] all measures match. Keep this table on a hidden page.

## Stage 4 — Report pages (3–4 h)

Canvas 16:9. One idea per page, stated in the title. Put filters in a row across the top of every page: a **fund slicer** and a **date slicer** (`dim_date[Date]`, style "Between"). If the web editor doesn't offer *Sync slicers*, put the same two slicers on each page.

Theme: if **View → Themes → Browse for themes** is available, load `powerbi/theme_esg.json`. If not, set colours by hand: **ESG = green `#008300`, Conventional / benchmark = blue `#2a78d6`**. Use them consistently on every page, and always add a legend or direct label, so identity never relies on colour alone.

### Page 1 — "Has ethical cost returns?"
- Fund slicer: `dim_fund[short_name]`, with a slicer filter `category` = ESG, **single select**.
- Card: `Headline Gap Text` (big). Under it, `Selected Period`.
- Four KPI pairs: CAGR vs Benchmark CAGR · Sharpe vs Benchmark Sharpe · Ann. Volatility vs Benchmark Ann. Volatility · Max Drawdown vs Benchmark Max Drawdown.
- Line chart: x = `dim_date[Date]`, y = `Growth of £10k` and `Benchmark Growth of £10k`. Rename the series to "ESG fund" and "Conventional benchmark".
- Page filter: `in_pair_period` is 1.
- Small text: "Historical analysis in GBP, dividends reinvested. Not investment advice."

### Page 2 — "When did the gap open?"
- Column chart: x = `dim_date[Date]`, y = `Rolling 12M Gap vs Benchmark`. Conditional colour: green above 0, red below.
- Line chart: `Drawdown` and `Benchmark Drawdown` over `dim_date[Date]`.
- Line chart: `Rolling 36M Sharpe`.

### Page 3 — "Which market conditions hurt or helped?"
- Matrix: rows = `dim_date[Regime]`. Values = `Cumulative Return`, `Benchmark Cumulative Return`, `Return Gap vs Benchmark`, `Win Rate vs Benchmark`.
- Bar chart: `Return Gap vs Benchmark` by `Regime`, with green/red conditional colour.
- Callout: the 2022 energy shock is where low-fossil-fuel funds should lag. Do they?

### Page 4 — "All funds, same period"
- Page filter: `in_common_period` is 1, so every fund is measured over the same months.
- Table: rows `dim_fund[short_name]`. Columns: `category`, `CAGR`, `Ann. Volatility`, `Sharpe Ratio`, `Sortino Ratio`, `Max Drawdown`, `Fund TER`.
- Scatter: x = `Ann. Volatility`, y = `CAGR`, values/details = `short_name`, legend = `category`, with data labels on.

### Page 5 — "Why: sector tilts"
- Bar chart: `Sector Tilt vs Benchmark` by `fact_sector_weights[Sector]`, sorted, with green/red conditional colour.
- Note on the page: these are current weights, not history.

### Page 6 — "Method and limitations"
Text only. Data sources, the GBP conversion of the EUR/USD-quoted lines, SONIA as the risk-free rate, the short sample (under 9 years, about 5½ for the Vanguard pair), market price vs NAV, and "not investment advice".

## Stage 5 — Ship it (1–2 h)

- [ ] Titles are statements, not labels ("ESG lagged in 2022", not "Regime chart").
- [ ] Add alt text to each visual (Format → General → Alt text).
- [ ] **Export → PDF** → save as `powerbi/ESG_vs_Conventional.pdf` and commit it.
- [ ] Screenshots of each page → `figures/` → into the README.
- [ ] Record a 2-minute walkthrough (macOS: Shift+Cmd+5; Windows: Win+G). Put the link in the README.
- [ ] Sharing a live link with Tom needs Pro, or Pro-trial, for both of you. Otherwise, send the PDF and video.

## If something breaks

| Symptom | Likely cause |
|---|---|
| "Open data model" greyed out | My workspace or tenant setting; see Stage 1 |
| Growth line flat at £10,000 | x-axis isn't a `dim_date` column, or the Date relationship is missing |
| Benchmark measures blank for an ESG fund | `BenchmarkReturn` loaded as text, or blanks became 0 |
| Numbers differ slightly from Python | `in_pair_period` filter missing, or a date slicer is active |
| CAGR blank | fewer than 12 months selected (by design; use Cumulative Return) |
| New sector weights don't appear | re-run the export, overwrite the file on OneDrive, then **Refresh** the semantic model |
