"""Tests for portfolio_drawdown_backtest.py — TDD red-green cycle."""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

# Add scripts dir to path so we can import the module
sys.path.insert(0, os.path.dirname(__file__))
import portfolio_drawdown_backtest as pdb


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def minimal_portfolio_json(tmp_path):
    """Create a minimal 3-position portfolio JSON file."""
    data = {
        "positions": [
            {
                "name": "SGOV (0-3M Treasury)",
                "ticker": "SGOV",
                "weight": 0.5,
                "asset_class": "Short-term bonds",
                "proxy_map": {"dotcom": "_TBILL", "gfc": "_TBILL", "covid": "_TBILL"},
            },
            {
                "name": "SGOL (Gold)",
                "ticker": "SGOL",
                "weight": 0.3,
                "asset_class": "Gold",
                "proxy_map": {"dotcom": "GC=F", "gfc": "GC=F", "covid": "GC=F"},
            },
            {
                "name": "VTI (US Total Market)",
                "ticker": "VTI",
                "weight": 0.2,
                "asset_class": "US equity",
                "proxy_map": {"dotcom": "SPY", "gfc": "VTI", "covid": "VTI"},
            },
        ],
        "metadata": {
            "source": "hiro",
            "fetched_at": "2026-03-08T12:00:00",
            "total_value": 100000,
        },
    }
    path = tmp_path / "portfolio.json"
    path.write_text(json.dumps(data))
    return path


@pytest.fixture
def unnormalized_portfolio_json(tmp_path):
    """Portfolio with weights that don't sum to 1."""
    data = {
        "positions": [
            {"name": "A", "ticker": "SGOV", "weight": 2.0, "asset_class": "Short-term bonds", "proxy_map": {}},
            {"name": "B", "ticker": "VTI", "weight": 3.0, "asset_class": "US equity", "proxy_map": {}},
        ],
        "metadata": {"source": "test"},
    }
    path = tmp_path / "portfolio.json"
    path.write_text(json.dumps(data))
    return path


@pytest.fixture
def missing_fields_portfolio_json(tmp_path):
    """Portfolio JSON with missing optional fields (no proxy_map)."""
    data = {
        "positions": [
            {"name": "SGOV", "ticker": "SGOV", "weight": 0.6, "asset_class": "Short-term bonds"},
            {"name": "VTI", "ticker": "VTI", "weight": 0.4, "asset_class": "US equity"},
        ],
        "metadata": {"source": "test"},
    }
    path = tmp_path / "portfolio.json"
    path.write_text(json.dumps(data))
    return path


# ── Test 1: load_portfolio_from_json ──────────────────────────────────

def test_load_portfolio_from_json(minimal_portfolio_json):
    """Loading a valid JSON produces list-of-tuples matching PORTFOLIO format."""
    portfolio = pdb.load_portfolio_from_json(str(minimal_portfolio_json))

    assert isinstance(portfolio, list)
    assert len(portfolio) == 3

    # Each entry should be (name, ticker, weight, asset_class, proxy_map)
    for entry in portfolio:
        assert len(entry) == 5
        name, ticker, weight, asset_class, proxy_map = entry
        assert isinstance(name, str)
        assert isinstance(ticker, str)
        assert isinstance(weight, float)
        assert isinstance(asset_class, str)
        assert proxy_map is None or isinstance(proxy_map, dict)

    # Check weights are normalized to sum to 1.0
    total = sum(w for _, _, w, _, _ in portfolio)
    assert abs(total - 1.0) < 1e-9


def test_load_portfolio_from_json_normalizes_weights(unnormalized_portfolio_json):
    """Weights that don't sum to 1 are normalized."""
    portfolio = pdb.load_portfolio_from_json(str(unnormalized_portfolio_json))
    total = sum(w for _, _, w, _, _ in portfolio)
    assert abs(total - 1.0) < 1e-9

    # Original ratio 2:3 should be preserved
    assert abs(portfolio[0][2] - 0.4) < 1e-9
    assert abs(portfolio[1][2] - 0.6) < 1e-9


# ── Test 2: Missing optional fields ──────────────────────────────────

def test_load_portfolio_json_missing_fields(missing_fields_portfolio_json):
    """JSON with missing proxy_map should default to None."""
    portfolio = pdb.load_portfolio_from_json(str(missing_fields_portfolio_json))

    assert len(portfolio) == 2
    for entry in portfolio:
        name, ticker, weight, asset_class, proxy_map = entry
        assert proxy_map is None


# ── Test 3: argparse defaults ─────────────────────────────────────────

def test_argparse_defaults():
    """No args should give default portfolio path (None), default output dir, all periods."""
    args = pdb.parse_args([])
    assert args.portfolio_json is None
    assert args.output_dir is None
    assert args.periods == "dotcom,gfc,covid"
    assert args.no_html is False


# ── Test 4: argparse custom periods ───────────────────────────────────

def test_argparse_custom_periods():
    """--periods gfc,covid should parse correctly."""
    args = pdb.parse_args(["--periods", "gfc,covid"])
    assert args.periods == "gfc,covid"

    # The parsed periods should split to a list
    periods = args.periods.split(",")
    assert periods == ["gfc", "covid"]


def test_argparse_portfolio_json():
    """--portfolio-json path should be stored."""
    args = pdb.parse_args(["--portfolio-json", "/tmp/test.json"])
    assert args.portfolio_json == "/tmp/test.json"


def test_argparse_output_dir():
    """--output-dir should be stored."""
    args = pdb.parse_args(["--output-dir", "/tmp/output"])
    assert args.output_dir == "/tmp/output"


def test_argparse_no_html():
    """--no-html flag should be True when passed."""
    args = pdb.parse_args(["--no-html"])
    assert args.no_html is True


# ── Test 5: calc_drawdown_stats with known values ─────────────────────

def test_calc_drawdown_stats_known_values():
    """Known price series: 100 → 80 → 120 should give max_dd=-20%, total_return=20%."""
    dates = pd.bdate_range("2020-01-01", periods=3)
    prices = pd.Series([100.0, 80.0, 120.0], index=dates)

    stats = pdb.calc_drawdown_stats(prices)

    assert abs(stats["max_drawdown"] - (-20.0)) < 0.1
    assert abs(stats["total_return"] - 20.0) < 0.1
    assert stats["peak_date"] == dates[0]
    assert stats["trough_date"] == dates[1]


def test_calc_drawdown_stats_no_drawdown():
    """Monotonically increasing prices should have max_dd=0."""
    dates = pd.bdate_range("2020-01-01", periods=5)
    prices = pd.Series([100.0, 110.0, 120.0, 130.0, 140.0], index=dates)

    stats = pdb.calc_drawdown_stats(prices)

    assert stats["max_drawdown"] == 0.0
    assert abs(stats["total_return"] - 40.0) < 0.1


# ── Test 6: calc_drawdown_stats with None input ──────────────────────

def test_calc_drawdown_stats_none_input():
    """None input should return all-zero dict."""
    stats = pdb.calc_drawdown_stats(None)

    assert stats["max_drawdown"] == 0
    assert stats["total_return"] == 0
    assert stats["peak_date"] is None
    assert stats["trough_date"] is None
    assert stats["recovery_date"] is None


def test_calc_drawdown_stats_single_point():
    """Single data point should return zeros."""
    dates = pd.bdate_range("2020-01-01", periods=1)
    prices = pd.Series([100.0], index=dates)

    stats = pdb.calc_drawdown_stats(prices)
    assert stats["max_drawdown"] == 0
    assert stats["total_return"] == 0


# ── Test 7: simulate_with_volatility shape ────────────────────────────

def test_simulate_with_volatility_shape():
    """Output should be a pd.Series with correct date range and non-zero variance."""
    result = pdb.simulate_with_volatility(
        "2020-01-01", "2020-06-01",
        annual_return=0.05, annual_vol=0.15, seed=42,
    )

    assert isinstance(result, pd.Series)
    assert len(result) > 50  # ~5 months of business days
    assert result.std() > 0  # non-zero variance
    assert result.iloc[0] > 0  # starts positive
    assert result.index[0] >= pd.Timestamp("2020-01-01")
    assert result.index[-1] <= pd.Timestamp("2020-06-01") + pd.Timedelta(days=1)


def test_simulate_with_volatility_deterministic():
    """Same seed should produce identical results."""
    a = pdb.simulate_with_volatility("2020-01-01", "2020-03-01", 0.05, 0.10, seed=99)
    b = pdb.simulate_with_volatility("2020-01-01", "2020-03-01", 0.05, 0.10, seed=99)
    pd.testing.assert_series_equal(a, b)


# ── Test 8: simulate_em_equity returns tuple ──────────────────────────

def test_em_equity_basket_returns_tuple():
    """simulate_em_equity should return (series, label) tuple."""
    # Mock get_price_data to avoid network calls
    fake_dates = pd.bdate_range("2020-01-01", "2020-06-01")
    fake_prices = pd.Series(np.random.RandomState(42).uniform(90, 110, len(fake_dates)), index=fake_dates)

    with patch.object(pdb, "get_price_data", return_value=fake_prices):
        result = pdb.simulate_em_equity("2020-01-01", "2020-06-01")

    assert isinstance(result, tuple)
    assert len(result) == 2
    series, label = result
    assert isinstance(series, pd.Series)
    assert isinstance(label, str)
    assert len(series) > 0


# ── Test 9: output files created ──────────────────────────────────────

def test_output_files_created(minimal_portfolio_json, tmp_path):
    """Run with a small fixture and --no-html; assert data.json and summary.md are written."""
    output_dir = tmp_path / "output"

    # Mock run_backtest to avoid network calls, return minimal results
    fake_results = {}
    for period_key in ["dotcom", "gfc", "covid"]:
        dates = pd.bdate_range("2020-01-01", periods=10)
        portfolio_series = pd.Series(np.linspace(100, 95, 10), index=dates)
        sp500_prices = pd.Series(np.linspace(100, 85, 10), index=dates)
        fake_results[period_key] = {
            "period": pdb.DRAWDOWNS[period_key],
            "securities": [
                {"name": "Test", "ticker": "TEST", "weight": 1.0,
                 "asset_class": "Test", "source": "test",
                 "max_drawdown": -5.0, "total_return": -5.0,
                 "peak_date": dates[0], "trough_date": dates[-1],
                 "recovery_date": None}
            ],
            "portfolio_series": portfolio_series,
            "portfolio_stats": pdb.calc_drawdown_stats(portfolio_series),
            "sp500_prices": sp500_prices,
            "sp500_stats": pdb.calc_drawdown_stats(sp500_prices),
        }

    with patch.object(pdb, "run_backtest", return_value=fake_results):
        pdb.main([
            "--portfolio-json", str(minimal_portfolio_json),
            "--output-dir", str(output_dir),
            "--no-html",
        ])

    # Files are timestamped: yyyy-mm-dd-hhmm-data.json, yyyy-mm-dd-hhmm-summary.md
    data_files = list(output_dir.glob("*-data.json"))
    md_files = list(output_dir.glob("*-summary.md"))
    assert len(data_files) == 1, f"Expected 1 data JSON file, found {data_files}"
    assert len(md_files) == 1, f"Expected 1 summary MD file, found {md_files}"
    # Verify data.json is valid JSON
    data = json.loads(data_files[0].read_text())
    assert "dotcom" in data or "results" in data


# ── Test 10: backward compat — no args uses hardcoded PORTFOLIO ───────

def test_backward_compat_no_args():
    """Calling with no JSON input should use the hardcoded PORTFOLIO."""
    # The PORTFOLIO constant should exist and be non-empty
    assert hasattr(pdb, "PORTFOLIO")
    assert len(pdb.PORTFOLIO) > 0

    # Each entry should be a 5-tuple
    for entry in pdb.PORTFOLIO:
        assert len(entry) == 5

    # Weights should sum to ~1.0
    total = sum(w for _, _, w, _, _ in pdb.PORTFOLIO)
    assert abs(total - 1.0) < 0.01


# ── Item 1: Dynamic resilience assessment ──────────────────────────────

def test_markdown_report_no_hardcoded_allocations():
    """Custom portfolio must NOT produce hardcoded gold/tbill/sogo shosha text."""
    dates = pd.bdate_range("2020-01-01", periods=10)
    portfolio_series = pd.Series(np.linspace(100, 90, 10), index=dates)
    sp500_prices = pd.Series(np.linspace(100, 80, 10), index=dates)

    fake_results = {
        "covid": {
            "period": pdb.DRAWDOWNS["covid"],
            "securities": [
                {"name": "VTI", "ticker": "VTI", "weight": 1.0,
                 "asset_class": "US equity", "source": "VTI",
                 "max_drawdown": -10.0, "total_return": -10.0},
            ],
            "portfolio_series": portfolio_series,
            "portfolio_stats": pdb.calc_drawdown_stats(portfolio_series),
            "sp500_prices": sp500_prices,
            "sp500_stats": pdb.calc_drawdown_stats(sp500_prices),
        }
    }

    with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
        output_path = f.name

    try:
        portfolio = [("VTI", "VTI", 1.0, "US equity", None)]
        pdb.generate_markdown_report(fake_results, output_path, portfolio=portfolio)
        content = Path(output_path).read_text()

        # Should NOT contain hardcoded references to specific allocations
        assert "gold (20%)" not in content.lower()
        assert "T-bills (16%)" not in content
        assert "sogo shosha (14%)" not in content.lower()
        # Should contain the actual allocation
        assert "US equity" in content
    finally:
        os.unlink(output_path)


# ── Item 2: Consistent simulator return types ──────────────────────────

def test_all_proxy_simulators_return_tuples():
    """All PROXY_SIMULATORS should return (Series, str) tuples."""
    start, end = "2020-01-01", "2020-06-01"

    # Return None to force simulation path (where return types were inconsistent)
    with patch.object(pdb, "get_price_data", return_value=None):
        for key, func in pdb.PROXY_SIMULATORS.items():
            result = func(start, end)
            assert isinstance(result, tuple), f"{key} should return a tuple, got {type(result)}"
            assert len(result) == 2, f"{key} should return 2-tuple"
            series, label = result
            assert isinstance(series, pd.Series), f"{key}[0] should be Series"
            assert isinstance(label, str), f"{key}[1] should be str"


# ── Item 3: group_by_asset_class ───────────────────────────────────────

def test_group_by_asset_class():
    """group_by_asset_class should aggregate weight, drawdown, and return."""
    securities = [
        {"asset_class": "Gold", "weight": 0.10, "max_drawdown": -5.0, "total_return": 10.0},
        {"asset_class": "Gold", "weight": 0.10, "max_drawdown": -3.0, "total_return": 8.0},
        {"asset_class": "US equity", "weight": 0.30, "max_drawdown": -40.0, "total_return": -30.0},
    ]
    groups = pdb.group_by_asset_class(securities)

    assert "Gold" in groups
    assert "US equity" in groups
    assert abs(groups["Gold"]["weight"] - 0.20) < 1e-9
    # weighted_dd = 0.10 * -5.0 + 0.10 * -3.0 = -0.8
    assert abs(groups["Gold"]["weighted_dd"] - (-0.8)) < 1e-9
    assert abs(groups["US equity"]["weight"] - 0.30) < 1e-9
    assert abs(groups["US equity"]["weighted_dd"] - (0.30 * -40.0)) < 1e-9


# ── Item 4: Late-starting series backfilled with initial value ────────

def test_late_start_backfills_initial_value():
    """Late-starting series should be backfilled with weight * 1.0 (the
    neutral 'hasn't moved yet' assumption), so the portfolio starts at 1.0
    and doesn't spike when the late series appears.
    """
    dates = pd.bdate_range("2020-01-01", periods=5)

    # Series A (weight 0.5): full date range
    prices_a = pd.Series([100, 102, 104, 106, 108], index=dates, dtype=float)
    norm_a = prices_a / prices_a.iloc[0]
    weighted_a = norm_a * 0.5

    # Series B (weight 0.5): starts on day 3
    prices_b = pd.Series([100, 98, 96], index=dates[2:], dtype=float)
    norm_b = prices_b / prices_b.iloc[0]
    weighted_b = norm_b * 0.5

    portfolio = pdb.combine_weighted_series([weighted_a, weighted_b])

    # Day 1: A contributes 0.5, B backfilled at 0.5 (weight * 1.0) → total 1.0
    assert abs(portfolio.iloc[0] - 1.0) < 1e-9

    # B's backfilled days should be flat at its weight (no future prices leaked)
    # Day 1 and Day 2 both have B at 0.5 (its initial normalized * weight value)
    day1_b_contribution = portfolio.iloc[0] - weighted_a.iloc[0]
    day2_b_contribution = portfolio.iloc[1] - weighted_a.iloc[1]
    assert abs(day1_b_contribution - 0.5) < 1e-9
    assert abs(day2_b_contribution - 0.5) < 1e-9


# ── Item 11: Late-starting securities should not cause spikes ─────────

def test_late_start_no_spike():
    """When a security (~15% weight) starts a few days late, the portfolio
    should NOT spike when its data appears.

    Bug: combine_weighted_series ffills but doesn't bfill, so NaN before
    a security's first data point → 0 contribution → sudden jump when
    data appears. E.g. GC=F (gold, ~19%) missing at start of dot-com.
    """
    dates = pd.bdate_range("2020-01-01", periods=10)

    # 4 securities with full data (85% total weight)
    full_series = []
    for i, w in enumerate([0.40, 0.25, 0.12, 0.08]):
        prices = pd.Series(
            np.linspace(100, 100 - i * 2, 10), index=dates, dtype=float
        )
        norm = prices / prices.iloc[0]
        full_series.append(norm * w)

    # 1 security (15% weight) starts on day 4
    late_prices = pd.Series(
        np.linspace(100, 95, 7), index=dates[3:], dtype=float
    )
    norm_late = late_prices / late_prices.iloc[0]
    late_series = norm_late * 0.15

    portfolio = pdb.combine_weighted_series(full_series + [late_series])

    # Portfolio should start near 1.0, not 0.85
    assert portfolio.iloc[0] > 0.95, (
        f"Portfolio starts at {portfolio.iloc[0]:.4f} — "
        f"missing late-start security weight"
    )

    # No single-day jump > 5% (the spike when late security appears)
    daily_returns = portfolio.pct_change().dropna()
    max_jump = daily_returns.abs().max()
    assert max_jump < 0.05, (
        f"Max single-day change is {max_jump:.1%} — "
        f"late-starting security caused a spike"
    )


# ── Item 5: dd_color ──────────────────────────────────────────────────

def test_dd_color():
    """dd_color returns correct hex codes for each drawdown bucket."""
    assert pdb.dd_color(-2) == "#16a34a"   # green: > -5
    assert pdb.dd_color(-10) == "#ca8a04"  # yellow: > -20
    assert pdb.dd_color(-30) == "#dc2626"  # red: <= -20
    assert pdb.dd_color(0) == "#16a34a"    # green: no drawdown
    assert pdb.dd_color(-5) == "#ca8a04"   # yellow: exactly -5
    assert pdb.dd_color(-20) == "#dc2626"  # red: exactly -20


# ── Item 6: FX fallback rate ──────────────────────────────────────────

def test_fx_fallback_rates_per_period():
    """FX_FALLBACK_RATES should have different rates per period, not hardcoded 150."""
    assert hasattr(pdb, "FX_FALLBACK_RATES")
    assert "dotcom" in pdb.FX_FALLBACK_RATES
    assert "gfc" in pdb.FX_FALLBACK_RATES
    assert "covid" in pdb.FX_FALLBACK_RATES
    # Period rates should differ from old hardcoded 150
    assert pdb.FX_FALLBACK_RATES["dotcom"] != 150.0
    assert pdb.FX_FALLBACK_RATES["gfc"] != 150.0


def test_fx_fallback_logs_warning(capsys):
    """FX fallback should print a warning when using fallback rate."""
    dates = pd.bdate_range("2020-01-01", periods=10)
    prices = pd.Series(np.linspace(1000, 1100, 10), index=dates)

    with patch.object(pdb, "get_price_data", return_value=prices):
        result_prices, source = pdb.get_security_prices(
            "Mitsui", "8031.T", None, "covid", "2020-01-01", "2020-06-01",
            fx_rate=None,
        )

    captured = capsys.readouterr()
    assert "warning" in captured.out.lower()
    assert "fallback" in captured.out.lower()


# ── Item 7: SIMULATOR_PARAMS ──────────────────────────────────────────

def test_simulator_params_exists():
    """SIMULATOR_PARAMS config dict should contain params for all simulator types."""
    assert hasattr(pdb, "SIMULATOR_PARAMS")
    params = pdb.SIMULATOR_PARAMS
    expected_keys = ["tbill", "lt_treasury", "tips", "gsci",
                     "intl_bonds", "em_bonds_gfc", "em_bonds_dotcom",
                     "em_equity_fallback"]
    for key in expected_keys:
        assert key in params, f"Missing key: {key}"


# ── Item 8: normalize helper ──────────────────────────────────────────

def test_normalize_default_base():
    """normalize() should scale to start at 1.0 by default."""
    prices = pd.Series([50.0, 100.0, 75.0])
    result = pdb.normalize(prices)
    assert abs(result.iloc[0] - 1.0) < 1e-9
    assert abs(result.iloc[1] - 2.0) < 1e-9
    assert abs(result.iloc[2] - 1.5) < 1e-9


def test_normalize_custom_base():
    """normalize(base=100) should scale to start at 100."""
    prices = pd.Series([50.0, 100.0, 75.0])
    result = pdb.normalize(prices, base=100)
    assert abs(result.iloc[0] - 100.0) < 1e-9
    assert abs(result.iloc[1] - 200.0) < 1e-9


def test_normalize_none_input():
    """normalize(None) should return None."""
    assert pdb.normalize(None) is None


# ── Item 9: END_DATE_BUFFER_DAYS ──────────────────────────────────────

def test_end_date_buffer_constant():
    """END_DATE_BUFFER_DAYS constant should exist and be positive."""
    assert hasattr(pdb, "END_DATE_BUFFER_DAYS")
    assert pdb.END_DATE_BUFFER_DAYS > 0


# ── Item 10: Crypto weekend/holiday sparse-row bug ───────────────────

def test_crypto_weekend_rows_do_not_inflate_returns():
    """BTC trades on weekends when nothing else does. If those sparse rows
    aren't dropped, the portfolio sum starts at just BTC's weight (~0.01)
    and jumps to ~1.0 on the next trading day — a fake 8000%+ return.

    The portfolio combiner must drop rows where <50% of series have data
    so that weekend-only crypto rows don't distort the result.
    """
    # BTC trades on Jan 1 (New Year's) and Jan 2, stocks start Jan 2
    # This is the actual bug: BTC has data BEFORE stocks, so ffill can't
    # fill stocks backward and the sum on Jan 1 is just BTC's weight
    all_dates = pd.date_range("2020-01-01", periods=5, freq="D")  # Jan 1-5
    stock_dates = all_dates[1:]  # Jan 2-5 (stocks start a day later)

    # Stock A (weight 0.50): starts Jan 2
    stock_prices = pd.Series([100.0, 99.0, 98.0, 97.0], index=stock_dates)
    norm_stock = stock_prices / stock_prices.iloc[0]
    weighted_stock = norm_stock * 0.50

    # Stock B (weight 0.49): starts Jan 2
    stock2_prices = pd.Series([100.0, 101.0, 102.0, 103.0], index=stock_dates)
    norm_stock2 = stock2_prices / stock2_prices.iloc[0]
    weighted_stock2 = norm_stock2 * 0.49

    # BTC (weight 0.01): trades every day including Jan 1
    btc_prices = pd.Series([100.0, 99.0, 101.0, 102.0, 100.0], index=all_dates)
    norm_btc = btc_prices / btc_prices.iloc[0]
    weighted_btc = norm_btc * 0.01

    all_weighted_series = [weighted_stock, weighted_stock2, weighted_btc]

    # Use the production combination function
    portfolio_series = pdb.combine_weighted_series(all_weighted_series)

    # The portfolio should start near 1.0 (sum of all weights), NOT at 0.01
    assert portfolio_series.iloc[0] > 0.9, (
        f"Portfolio starts at {portfolio_series.iloc[0]:.4f} — "
        f"sparse weekend rows with only crypto are inflating returns"
    )

    # Total return should be reasonable, not thousands of percent
    total_return = (portfolio_series.iloc[-1] / portfolio_series.iloc[0] - 1) * 100
    assert abs(total_return) < 50, (
        f"Total return is {total_return:.0f}% — "
        f"crypto weekend rows are creating fake returns"
    )
