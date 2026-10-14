"""
Tests for the cleaning pipeline, using small synthetic series so they run
offline. Run with:  pytest -q
"""
import numpy as np
import pandas as pd
import pytest

from src import build_dataset, cleaning, config, data_loader


def bdays(start="2017-10-16", end="2018-03-31"):
    return pd.bdate_range(start, end)


# ---------------------------------------------------------------- units
def test_pence_to_pounds():
    s = pd.Series([4500.0, 4510.0], name="CONV")
    out, ccy = cleaning.to_major_units(s, "GBp")
    assert ccy == "GBP" and out.tolist() == [45.0, 45.1]


def test_unit_glitch_is_repaired():
    idx = bdays()
    s = pd.Series(45.0, index=idx, name="CONV")
    s.iloc[30] = 4500.0          # one day quoted in pence by mistake
    s.iloc[60] = 0.45            # one day 100x too small
    log = cleaning.QualityLog()
    fixed = cleaning.fix_unit_glitches(s, log)
    assert np.allclose(fixed, 45.0)
    assert "rescaled 2 day" in str(log)


# ---------------------------------------------------------------- currency
def test_eur_to_gbp_uses_last_available_rate():
    idx = pd.to_datetime(["2020-01-06", "2020-01-07", "2020-01-08"])
    price = pd.Series([10.0, 10.0, 10.0], index=idx, name="SRI")
    fx = pd.Series([0.85, 0.90], index=pd.to_datetime(["2020-01-03", "2020-01-07"]))
    out = cleaning.convert_to_gbp(price, fx, cleaning.QualityLog())
    assert out.tolist() == pytest.approx([8.5, 9.0, 9.0])


# ---------------------------------------------------------------- alignment
def test_align_starts_at_common_date_and_fills_short_gaps():
    idx = bdays("2017-10-02", "2017-12-29")
    a = pd.Series(1.0, index=idx, name="SRI")
    a.loc[:"2017-10-13"] = np.nan              # SRI not yet listed
    b = pd.Series(2.0, index=idx, name="CONV")
    b.iloc[40:42] = np.nan                     # 2-day gap -> filled
    log = cleaning.QualityLog()
    out = cleaning.align_prices(pd.concat([a, b], axis=1), log)
    assert out.index.min() == pd.Timestamp("2017-10-16")
    assert out.notna().all().all()


# ---------------------------------------------------------------- returns
def test_monthly_returns_use_month_end_prices_and_drop_first_month():
    idx = bdays("2017-10-16", "2018-01-31")
    p = pd.DataFrame({"X": np.linspace(100, 130, len(idx))}, index=idx)
    r = cleaning.monthly_returns(p, end="2018-01-31")
    me = p.resample("ME").last()["X"]
    assert r.index[0] == pd.Timestamp("2017-11-30")
    assert r["X"].iloc[0] == pytest.approx(me.iloc[1] / me.iloc[0] - 1)
    assert len(r) == 3


def test_incomplete_month_is_dropped():
    assert cleaning.last_complete_month_end(pd.Timestamp("2026-10-06")) == \
        pd.Timestamp("2026-09-30")


def test_sonia_compounds_over_calendar_days():
    # a flat 5% SONIA over all of 2019
    idx = pd.bdate_range("2019-01-01", "2019-12-31")
    sonia = pd.Series(5.0, index=idx)
    rf = cleaning.monthly_rf_from_sonia(sonia)
    jan = (1 + 0.05 / 365) ** 31 - 1
    assert rf.loc["2019-01-31"] == pytest.approx(jan)
    assert (1 + rf).prod() - 1 == pytest.approx((1 + 0.05 / 365) ** 365 - 1, rel=1e-6)


def test_gbp_to_usd_returns():
    idx = pd.date_range("2020-01-31", periods=3, freq="ME")
    r = pd.DataFrame({"X": [0.0, 0.10, 0.0]}, index=idx)
    fx_daily = pd.Series([1.30, 1.30, 1.43], index=idx)  # GBP +10% in Feb... then Mar
    out = cleaning.gbp_to_usd_returns(r.iloc[1:], fx_daily)
    assert out["X"].iloc[0] == pytest.approx(0.10)              # Feb: fx flat
    assert out["X"].iloc[1] == pytest.approx(0.10)              # Mar: fx +10%


# ---------------------------------------------------------------- French parser
FRENCH_SAMPLE = """This file was created using the 202608 Bloomberg database.
Missing data are indicated by -99.99.

,Mkt-RF,SMB,HML,RMW,CMA,RF
201710,   1.90,  -0.50,   0.10,   0.20,  -0.30,   0.09
201711,   2.00,  -0.10,  -0.20,   0.40,   0.10,   0.08

 Annual Factors: January-December
,Mkt-RF,SMB,HML,RMW,CMA,RF
2018,  -9.00,  -3.00,  -5.00,   1.00,   0.50,   1.80
"""


def test_french_parser_reads_only_monthly_table():
    df = data_loader.parse_french_csv(FRENCH_SAMPLE)
    assert list(df.columns) == ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "RF"]
    assert len(df) == 2
    assert df.index[0] == pd.Timestamp("2017-10-31")
    assert df.loc["2017-11-30", "Mkt-RF"] == pytest.approx(0.02)


# ---------------------------------------------------------------- end to end
def test_full_build_offline(tmp_path, monkeypatch):
    """Run build() with fake downloads to check the plumbing end to end."""
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2017-09-01", "2019-06-28")
    n = len(idx)
    conv_pence = 4000 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, n)))
    sri_eur = 45 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, n)))
    sri_eur[: idx.get_loc(pd.Timestamp("2017-10-16"))] = np.nan  # not yet listed
    conv_pence[100] /= 100  # a pence glitch
    prices = pd.DataFrame({"SUSW.L": sri_eur, "SWDA.L": conv_pence}, index=idx)
    fx = pd.DataFrame({"EURGBP": 0.88, "GBPUSD": 1.30}, index=idx)
    sonia = pd.Series(0.7, index=idx)
    ff = pd.DataFrame(0.01, index=pd.date_range("2017-01-31", "2019-03-31", freq="ME"),
                      columns=["Mkt-RF", "SMB", "HML", "RMW", "CMA", "RF", "WML"])

    monkeypatch.setattr(config, "DATA_PROCESSED", tmp_path)
    monkeypatch.setattr(data_loader, "download_fund_prices",
                        lambda refresh: (prices, {"SUSW.L": "EUR", "SWDA.L": "GBp"}))
    monkeypatch.setattr(data_loader, "download_fx", lambda refresh: fx)
    monkeypatch.setattr(data_loader, "download_sonia", lambda refresh: sonia)
    monkeypatch.setattr(data_loader, "download_ff_factors", lambda refresh: ff)
    monkeypatch.setattr(cleaning, "last_complete_month_end",
                        lambda today=None: pd.Timestamp("2019-05-31"))

    out = build_dataset.build(verbose=False)
    m = out["monthly"]
    assert m.index[0] == pd.Timestamp("2017-11-30")
    assert m.index[-1] == pd.Timestamp("2019-05-31")
    assert m[["SRI", "CONV", "RF"]].notna().all().all()
    assert m["CONV"].abs().max() < 0.5          # glitch did not leak into returns
    assert (tmp_path / "data_quality.md").exists()
    assert "pounds/pence glitch" in (tmp_path / "data_quality.md").read_text()


def test_sonia_month_ending_on_weekend_is_kept():
    # May 2026 ends on a Sunday; Friday 29th's fixing covers the weekend
    idx = pd.bdate_range("2026-01-01", "2026-05-29")
    rf = cleaning.monthly_rf_from_sonia(pd.Series(4.0, index=idx))
    assert rf.index[-1] == pd.Timestamp("2026-05-31")
    assert rf.iloc[-1] == pytest.approx((1 + 0.04 / 365) ** 31 - 1)
    # a month that genuinely is incomplete is still dropped
    idx2 = pd.bdate_range("2026-01-01", "2026-05-20")
    assert cleaning.monthly_rf_from_sonia(pd.Series(4.0, index=idx2)).index[-1] == \
        pd.Timestamp("2026-04-30")
