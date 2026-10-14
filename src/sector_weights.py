"""
Fill fact_sector_weights.csv from iShares holdings downloads.

On each fund's iShares page, use the Download button (gives "..._fund.xls") or the
holdings CSV link - both formats work, as does .xlsx.
Then run, for example:
    python -m src.sector_weights SWDA.L data/holdings/iShares-Core-MSCI-World-UCITS-ETF_fund.xls
    python -m src.sector_weights SUSW.L data/holdings/iShares-MSCI-World-SRI-UCITS-ETF-EUR-Acc_fund.xls

It adds up the 'Weight (%)' of every holding by 'Sector', converts to
decimals, and writes them (with the file's "as of" date) into
powerbi/data/fact_sector_weights.csv for that fund. Other funds' rows are
left untouched. Afterwards run:  python -m src.powerbi_export
"""
from __future__ import annotations

import csv
import html
import re
import io
import sys
from pathlib import Path

import pandas as pd

from .powerbi_export import GICS_SECTORS, PBI_DATA, load_fund_list

SECTOR_FILE = PBI_DATA / "fact_sector_weights.csv"


def _has_header(row: list[str]) -> bool:
    cells = [c.strip() for c in row]
    return "Sector" in cells and "Weight (%)" in cells


def _spreadsheetml_sheets(text: str) -> dict[str, list[list[str]]]:
    """Parse the XML 'Excel 2003' format that iShares' Download button gives
    (a .xls file that is really XML), with a regex so stray characters
    in the file can't break it."""
    sheets = {}
    for m in re.finditer(r'<(?:ss:)?Worksheet\b[^>]*?Name="([^"]*)"(.*?)</(?:ss:)?Worksheet>',
                         text, re.S):
        name, body = m.group(1), m.group(2)
        rows = []
        for r in re.finditer(r"<(?:ss:)?Row\b[^>]*?(?:/>|>(.*?)</(?:ss:)?Row>)", body, re.S):
            row = []
            for c in re.finditer(r"<(?:ss:)?Cell\b([^>]*?)(?:/>|>(.*?)</(?:ss:)?Cell>)",
                                 r.group(1) or "", re.S):
                idx = re.search(r'Index="(\d+)"', c.group(1))
                if idx:  # a skipped-column marker
                    row.extend([""] * (int(idx.group(1)) - 1 - len(row)))
                d = re.search(r"<(?:ss:)?Data[^>]*>(.*?)</(?:ss:)?Data>", c.group(2) or "", re.S)
                row.append(html.unescape(re.sub(r"<[^>]+>", "", d.group(1))).strip() if d else "")
            rows.append(row)
        sheets[name] = rows
    return sheets


def _load_rows(path: Path) -> list[list[str]]:
    """Return the rows of the sheet that holds the holdings table, as text."""
    raw = Path(path).read_bytes()
    if raw[:2] == b"PK":                                    # a real .xlsx
        sheets = pd.read_excel(path, sheet_name=None, header=None, dtype=str)
        candidates = {n: df.fillna("").values.tolist() for n, df in sheets.items()}
    else:
        text = raw.decode("utf-8-sig", errors="replace")
        if "<Workbook" in text[:5000] or "<ss:Workbook" in text[:5000]:
            candidates = _spreadsheetml_sheets(text)        # iShares "_fund.xls"
        else:
            candidates = {"csv": list(csv.reader(io.StringIO(text)))}   # holdings CSV
    ordered = sorted(candidates.items(), key=lambda kv: kv[0].lower() != "holdings")
    for name, rows in ordered:
        if any(_has_header(r) for r in rows):
            return rows
    raise SystemExit(f"No table with 'Sector' and 'Weight (%)' columns found in {path}. "
                     f"Sheets seen: {list(candidates)}")


def read_ishares_holdings(path: Path) -> tuple[pd.DataFrame, str | None]:
    """Read iShares holdings from a holdings CSV, the '_fund.xls' download, or .xlsx."""
    rows = _load_rows(path)
    header_i = next(i for i, r in enumerate(rows) if _has_header(r))
    as_of = None
    for r in rows[:header_i]:
        if r and "as of" in str(r[0]).lower() and len(r) > 1 and str(r[1]).strip():
            d = pd.to_datetime(str(r[1]).strip(), errors="coerce")
            as_of = None if pd.isna(d) else d.strftime("%Y-%m-%d")
    header = [c.strip() for c in rows[header_i]]
    body = [r[:len(header)] + [""] * (len(header) - len(r)) for r in rows[header_i + 1:]]
    df = pd.DataFrame(body, columns=header)
    df["Weight (%)"] = pd.to_numeric(df["Weight (%)"].astype(str).str.replace(",", ""),
                                     errors="coerce")
    df = df[df["Sector"].astype(str).str.strip().ne("") & df["Weight (%)"].notna()]
    return df, as_of


def sector_totals(holdings: pd.DataFrame) -> pd.Series:
    w = holdings.groupby(holdings["Sector"].str.strip())["Weight (%)"].sum() / 100
    # every standard sector gets a row, 0 if the fund holds none (e.g. Energy in
    # a fossil-fuel-free fund) - otherwise that sector vanishes from the chart
    w = w.reindex(list(dict.fromkeys(GICS_SECTORS + list(w.index))), fill_value=0.0)
    return w.sort_values(ascending=False)


def update_sector_file(ticker: str, weights: pd.Series, as_of: str | None) -> pd.DataFrame:
    funds = load_fund_list().set_index("ticker")
    if ticker not in funds.index:
        raise SystemExit(f"{ticker} is not in config/funds.csv")
    key = int(funds.loc[ticker, "fund_key"])
    table = pd.read_csv(SECTOR_FILE)
    table = table[table["fund_key"] != key]                      # replace this fund's rows
    new = pd.DataFrame({"fund_key": key, "ticker": ticker, "Sector": weights.index,
                        "Weight": weights.round(6).values, "AsOf": as_of})
    table = pd.concat([table, new], ignore_index=True).sort_values(["fund_key", "Sector"])
    table.to_csv(SECTOR_FILE, index=False)
    return new


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python -m src.sector_weights TICKER path/to/holdings.csv")
    ticker, path = sys.argv[1], Path(sys.argv[2]).expanduser()
    holdings, as_of = read_ishares_holdings(path)
    w = sector_totals(holdings)
    update_sector_file(ticker, w, as_of)
    print(f"{ticker}: {len(holdings)} holdings, as of {as_of or 'unknown date'}")
    print((w * 100).round(2).to_string())
    total = w.sum()
    print(f"Total: {total:.1%}" + ("" if 0.97 <= total <= 1.03
                                   else "  <- not close to 100%, check the file"))
