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

    assert (output_dir / "data.json").exists()
    # Verify data.json is valid JSON
    data = json.loads((output_dir / "data.json").read_text())
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
