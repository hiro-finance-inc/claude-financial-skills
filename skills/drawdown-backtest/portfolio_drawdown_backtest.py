#!/usr/bin/env python3
"""
Portfolio Drawdown Backtesting
Backtest current portfolio allocation against three major market drawdowns:
  - 2001 Dot-com crash
  - 2008 Global Financial Crisis
  - 2020 COVID crash

For securities that didn't exist during a period, proxies are used.
"""

import argparse
import warnings
warnings.filterwarnings("ignore")

import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import json
from pathlib import Path
from datetime import datetime, timedelta

# ── Portfolio definition ──────────────────────────────────────────────

# Example portfolio — override with --portfolio-json for live data from Hiro
PORTFOLIO = [
    # (name, ticker, weight, asset_class, proxy_map)
    # proxy_map: {period_name: proxy_ticker} or None if ticker works for all periods
    ("SGOV (0-3M Treasury)", "SGOV", 0.163, "Short-term bonds",
     {"dotcom": "_TBILL", "gfc": "_TBILL", "covid": "_TBILL"}),
    ("SGOL (Gold)", "SGOL", 0.103, "Gold",
     {"dotcom": "GC=F", "gfc": "GC=F", "covid": "GC=F"}),
    ("GLDM (Gold)", "GLDM", 0.100, "Gold",
     {"dotcom": "GC=F", "gfc": "GC=F", "covid": "GC=F"}),
    ("SPTL (Long Treasury)", "SPTL", 0.083, "Long-term bonds",
     {"dotcom": "_LT_TREASURY", "gfc": "TLT", "covid": "SPTL"}),
    ("LTPZ (15+ Yr TIPS)", "LTPZ", 0.080, "TIPS",
     {"dotcom": "_TIPS_PROXY", "gfc": "_TIPS_PROXY", "covid": "LTPZ"}),
    ("DBC (Commodities)", "DBC", 0.052, "Commodities",
     {"dotcom": "_GSCI_PROXY", "gfc": "DBC", "covid": "DBC"}),
    ("GUNR (Nat Resources)", "GUNR", 0.040, "Natural resources",
     {"dotcom": "XLE", "gfc": "XLE", "covid": "GUNR"}),
    ("VEA (Intl Developed)", "VEA", 0.036, "Intl developed equity",
     {"dotcom": "EFA", "gfc": "EFA", "covid": "VEA"}),
    ("Mitsui & Co", "8031.T", 0.033, "Japanese sogo shosha", None),
    ("Marubeni Corp", "8002.T", 0.031, "Japanese sogo shosha", None),
    ("Mitsubishi Corp", "8058.T", 0.029, "Japanese sogo shosha", None),
    ("IGOV (Intl Treasury)", "IGOV", 0.033, "Intl bonds",
     {"dotcom": "_INTL_BOND_PROXY", "gfc": "_INTL_BOND_PROXY", "covid": "IGOV"}),
    ("DEM (EM High Div)", "DEM", 0.028, "EM equity",
     {"dotcom": "_EM_EQUITY_PROXY", "gfc": "EEM", "covid": "DEM"}),
    ("Sumitomo Corp", "8053.T", 0.026, "Japanese sogo shosha", None),
    ("EMLC (EM Local Bonds)", "EMLC", 0.025, "EM bonds",
     {"dotcom": "_EM_BOND_PROXY", "gfc": "_EM_BOND_PROXY", "covid": "EMLC"}),
    ("IEMG (EM Core)", "IEMG", 0.025, "EM equity",
     {"dotcom": "_EM_EQUITY_PROXY", "gfc": "EEM", "covid": "IEMG"}),
    ("EBND (EM Bond)", "EBND", 0.024, "EM bonds",
     {"dotcom": "_EM_BOND_PROXY", "gfc": "EMB", "covid": "EBND"}),
    ("DGS (EM SmallCap)", "DGS", 0.023, "EM equity",
     {"dotcom": "_EM_EQUITY_PROXY", "gfc": "EEM", "covid": "DGS"}),
    ("Itochu Corp", "8001.T", 0.023, "Japanese sogo shosha", None),
    ("SRUUF (Uranium)", "SRUUF", 0.020, "Uranium",
     {"dotcom": "CCJ", "gfc": "CCJ", "covid": "CCJ"}),
    ("VTI (US Total Market)", "VTI", 0.035, "US equity",
     {"dotcom": "SPY", "gfc": "VTI", "covid": "VTI"}),
    ("VITNX (US Total Market)", "VITNX", 0.006, "US equity",
     {"dotcom": "SPY", "gfc": "SPY", "covid": "SPY"}),
    ("BTC (Bitcoin)", "BTC-USD", 0.012, "Crypto",
     {"dotcom": "_NO_DATA", "gfc": "_NO_DATA", "covid": "BTC-USD"}),
]

# Normalize weights to sum to 1 (excluding the negative cash position)
total_weight = sum(w for _, _, w, _, _ in PORTFOLIO)
PORTFOLIO = [(n, t, w / total_weight, ac, pm) for n, t, w, ac, pm in PORTFOLIO]

# ── Drawdown periods ─────────────────────────────────────────────────

DRAWDOWNS = {
    "dotcom": {
        "label": "2001 Dot-Com Crash",
        "start": "2000-03-01",
        "end": "2003-03-01",
        "sp500_dd": -49,
    },
    "gfc": {
        "label": "2008 Global Financial Crisis",
        "start": "2007-10-01",
        "end": "2009-06-01",
        "sp500_dd": -57,
    },
    "covid": {
        "label": "2020 COVID Crash",
        "start": "2020-01-01",
        "end": "2020-06-01",
        "sp500_dd": -34,
    },
}

# ── Constants ─────────────────────────────────────────────────────────

END_DATE_BUFFER_DAYS = 5

FX_FALLBACK_RATES = {
    "dotcom": 110.0,   # ~110 JPY/USD during 2000-2003
    "gfc": 100.0,      # ~90-110 JPY/USD during 2007-2009
    "covid": 108.0,    # ~105-110 JPY/USD during 2020
}
FX_FALLBACK_DEFAULT = 150.0

SIMULATOR_PARAMS = {
    "tbill": {
        "vol": 0.003,
        "rates": {2020: 0.01, 2007: 0.03, "default": 0.04},
    },
    "lt_treasury": {"return": 0.10, "vol": 0.10},
    "tips": {"return": 0.08, "vol": 0.06},
    "gsci": {"return": -0.10, "vol": 0.25},
    "intl_bonds": {"return": 0.05, "vol": 0.07},
    "em_bonds_gfc": {"return": -0.12, "vol": 0.15},
    "em_bonds_dotcom": {"return": 0.02, "vol": 0.12},
    "em_equity_fallback": {"return": -0.15, "vol": 0.25},
}

# ── Helpers ───────────────────────────────────────────────────────────


def normalize(prices, base=1.0):
    """Normalize a price series to start at `base`."""
    if prices is None or len(prices) == 0:
        return prices
    return prices / prices.iloc[0] * base


def dd_color(value):
    """Return hex color for a drawdown value: green (>-5%), yellow (>-20%), red."""
    if value > -5:
        return "#16a34a"
    elif value > -20:
        return "#ca8a04"
    else:
        return "#dc2626"


def group_by_asset_class(securities):
    """Group securities by asset class with aggregate weight, weighted drawdown, and weighted return.

    Returns: dict {asset_class: {"weight": float, "weighted_dd": float, "weighted_ret": float}}
    """
    groups = {}
    for s in securities:
        ac = s["asset_class"]
        if ac not in groups:
            groups[ac] = {"weight": 0, "weighted_dd": 0, "weighted_ret": 0}
        groups[ac]["weight"] += s["weight"]
        groups[ac]["weighted_dd"] += s["weight"] * s["max_drawdown"]
        groups[ac]["weighted_ret"] += s["weight"] * s["total_return"]
    return groups


# ── Portfolio JSON loading ────────────────────────────────────────────

def load_portfolio_from_json(path: str) -> list:
    """Load portfolio from a JSON file and return list-of-tuples matching PORTFOLIO format.

    Each tuple: (name, ticker, weight, asset_class, proxy_map)
    Weights are normalized to sum to 1.0.
    """
    with open(path) as f:
        data = json.load(f)

    positions = data["positions"]
    portfolio = []
    for p in positions:
        name = p["name"]
        ticker = p["ticker"]
        weight = float(p["weight"])
        asset_class = p["asset_class"]
        proxy_map = p.get("proxy_map") or None
        # Treat empty dict as None
        if proxy_map is not None and len(proxy_map) == 0:
            proxy_map = None
        portfolio.append((name, ticker, weight, asset_class, proxy_map))

    # Normalize weights to sum to 1.0
    total_weight = sum(w for _, _, w, _, _ in portfolio)
    if total_weight > 0 and abs(total_weight - 1.0) > 1e-9:
        portfolio = [(n, t, w / total_weight, ac, pm) for n, t, w, ac, pm in portfolio]

    return portfolio


def parse_args(argv: list = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Backtest portfolio allocation against major market drawdowns."
    )
    parser.add_argument(
        "--portfolio-json",
        type=str,
        default=None,
        help="Path to portfolio JSON file. If omitted, uses hardcoded portfolio.",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Output directory. If omitted, uses default paths.",
    )
    parser.add_argument(
        "--periods",
        type=str,
        default="dotcom,gfc,covid",
        help="Comma-separated list of crisis periods to backtest (default: dotcom,gfc,covid).",
    )
    parser.add_argument(
        "--no-html",
        action="store_true",
        default=False,
        help="Skip HTML dashboard generation.",
    )
    return parser.parse_args(argv)


# ── Data fetching ─────────────────────────────────────────────────────

def get_price_data(ticker: str, start: str, end: str) -> pd.Series | None:
    """Fetch adjusted close prices for a ticker."""
    try:
        # Extend end date by a few days to ensure we capture the full period
        end_dt = pd.Timestamp(end) + pd.Timedelta(days=END_DATE_BUFFER_DAYS)
        df = yf.download(ticker, start=start, end=end_dt.strftime("%Y-%m-%d"),
                         progress=False, auto_adjust=True)
        if df.empty:
            return None
        prices = df["Close"]
        if isinstance(prices, pd.DataFrame):
            prices = prices.iloc[:, 0]
        # Trim to actual end date
        prices = prices.loc[:end]
        return prices
    except Exception as e:
        print(f"  Warning: Failed to fetch {ticker}: {e}")
        return None


def get_fx_rate(start: str, end: str) -> pd.Series:
    """Fetch JPY/USD exchange rate."""
    end_dt = pd.Timestamp(end) + pd.Timedelta(days=END_DATE_BUFFER_DAYS)
    df = yf.download("JPYUSD=X", start=start, end=end_dt.strftime("%Y-%m-%d"),
                     progress=False, auto_adjust=True)
    if df.empty:
        # Fallback: use inverse of USDJPY
        df = yf.download("JPY=X", start=start, end=end_dt.strftime("%Y-%m-%d"),
                         progress=False, auto_adjust=True)
        if df.empty:
            return None
        rate = df["Close"]
        if isinstance(rate, pd.DataFrame):
            rate = rate.iloc[:, 0]
        rate = 1.0 / rate  # Convert USDJPY to JPYUSD
    else:
        rate = df["Close"]
        if isinstance(rate, pd.DataFrame):
            rate = rate.iloc[:, 0]
    return rate.loc[:end]


def try_tickers(tickers: list[str], start: str, end: str, min_points: int = 50) -> tuple[pd.Series | None, str | None]:
    """Try multiple tickers in order, return first one with enough data."""
    for t in tickers:
        prices = get_price_data(t, start, end)
        if prices is not None and len(prices) >= min_points:
            return prices, t
    return None, None


def simulate_with_volatility(start: str, end: str, annual_return: float,
                             annual_vol: float, seed: int = 42) -> pd.Series:
    """Simulate a price series with realistic drift and volatility."""
    rng = np.random.RandomState(seed)
    dates = pd.bdate_range(start, end)
    n = len(dates)
    daily_mu = annual_return / 252
    daily_sigma = annual_vol / np.sqrt(252)
    daily_returns = rng.normal(daily_mu, daily_sigma, n)
    prices = pd.Series(100.0 * np.cumprod(1 + daily_returns), index=dates)
    return prices


def simulate_tbill_returns(start: str, end: str) -> tuple[pd.Series, str]:
    """T-bills: near-zero drawdown, very low vol. Try SHV/BIL first."""
    prices, ticker = try_tickers(["SHV", "BIL"], start, end)
    if prices is not None:
        return prices, ticker
    year = int(start[:4])
    params = SIMULATOR_PARAMS["tbill"]
    if year >= 2020:
        annual_rate = params["rates"][2020]
    elif year >= 2007:
        annual_rate = params["rates"][2007]
    else:
        annual_rate = params["rates"]["default"]
    return simulate_with_volatility(start, end, annual_rate, params["vol"], seed=1), "Simulated (T-bill)"


def simulate_lt_treasury(start: str, end: str) -> tuple[pd.Series, str]:
    """Long treasuries. Try TLT (2002), else simulate with bond-like vol."""
    prices, ticker = try_tickers(["TLT"], start, end)
    if prices is not None:
        return prices, ticker
    p = SIMULATOR_PARAMS["lt_treasury"]
    return simulate_with_volatility(start, end, p["return"], p["vol"], seed=2), "Simulated (LT Treasury)"


def simulate_tips(start: str, end: str) -> tuple[pd.Series, str]:
    """TIPS. Try TIP ETF (2003), else simulate."""
    prices, ticker = try_tickers(["TIP"], start, end)
    if prices is not None:
        return prices, ticker
    p = SIMULATOR_PARAMS["tips"]
    return simulate_with_volatility(start, end, p["return"], p["vol"], seed=3), "Simulated (TIPS)"


def simulate_gsci(start: str, end: str) -> tuple[pd.Series, str]:
    """Commodity index proxy. Try crude oil futures, then DJP."""
    prices, ticker = try_tickers(["CL=F", "DJP"], start, end)
    if prices is not None:
        return prices, ticker
    p = SIMULATOR_PARAMS["gsci"]
    return simulate_with_volatility(start, end, p["return"], p["vol"], seed=4), "Simulated (GSCI)"


def simulate_intl_bonds(start: str, end: str) -> tuple[pd.Series, str]:
    """International government bonds. Try BWX (2007), IGOV, then simulate."""
    prices, ticker = try_tickers(["BWX", "IGOV"], start, end)
    if prices is not None:
        return prices, ticker
    p = SIMULATOR_PARAMS["intl_bonds"]
    return simulate_with_volatility(start, end, p["return"], p["vol"], seed=5), "Simulated (Intl bonds)"


def simulate_em_bonds(start: str, end: str) -> tuple[pd.Series, str]:
    """EM bonds. Try EMB (2007), PCY, VWOB, then simulate."""
    prices, ticker = try_tickers(["EMB", "PCY", "VWOB"], start, end)
    if prices is not None:
        return prices, ticker
    year = int(start[:4])
    if year >= 2007:
        p = SIMULATOR_PARAMS["em_bonds_gfc"]
        return simulate_with_volatility(start, end, p["return"], p["vol"], seed=6), "Simulated (EM bonds, GFC-era)"
    else:
        p = SIMULATOR_PARAMS["em_bonds_dotcom"]
        return simulate_with_volatility(start, end, p["return"], p["vol"], seed=7), "Simulated (EM bonds, dot-com era)"


def simulate_em_equity(start: str, end: str) -> pd.Series | None:
    """EM equity proxy using equal-weighted basket of country ETFs.
    EWZ alone is a poor proxy — Brazil was hit uniquely hard (Lula 2002).
    Basket better approximates MSCI EM (~-50% during dot-com)."""
    # Country ETFs that existed during dot-com (all launched pre-2000)
    em_tickers = ["EWZ", "EWH", "EWT", "EWY", "EWS", "EWM"]  # Brazil, HK, Taiwan, Korea, Singapore, Malaysia
    basket_series = []
    used_tickers = []
    for t in em_tickers:
        prices = get_price_data(t, start, end)
        if prices is not None and len(prices) >= 50:
            # Normalize each to 1.0
            norm = prices / prices.iloc[0]
            basket_series.append(norm)
            used_tickers.append(t)

    if basket_series:
        # Equal-weight basket: align all series and average
        df = pd.DataFrame({f"s{i}": s for i, s in enumerate(basket_series)})
        df = df.ffill().bfill()
        basket = df.mean(axis=1) * 100  # scale to price-like
        label = f"EM basket ({', '.join(used_tickers)})"
        print(f"    Using {label} as EM equity proxy")
        return basket, label

    # Fallback: simulate based on known MSCI EM performance
    p = SIMULATOR_PARAMS["em_equity_fallback"]
    return simulate_with_volatility(start, end, p["return"], p["vol"], seed=8), "Simulated (MSCI EM est.)"


PROXY_SIMULATORS = {
    "_TBILL": simulate_tbill_returns,
    "_LT_TREASURY": simulate_lt_treasury,
    "_TIPS_PROXY": simulate_tips,
    "_GSCI_PROXY": simulate_gsci,
    "_INTL_BOND_PROXY": simulate_intl_bonds,
    "_EM_BOND_PROXY": simulate_em_bonds,
    "_EM_EQUITY_PROXY": simulate_em_equity,
}


def get_security_prices(name: str, ticker: str, proxy_map: dict | None,
                        period_key: str, start: str, end: str,
                        fx_rate: pd.Series | None) -> tuple[pd.Series | None, str]:
    """Get prices for a security, using proxies as needed.
    Returns (price_series, source_label)."""
    is_jpy = ticker.endswith(".T")

    # Determine which ticker to use
    if proxy_map and period_key in proxy_map:
        use_ticker = proxy_map[period_key]
    else:
        use_ticker = ticker

    # Handle special proxy simulators
    if use_ticker == "_NO_DATA":
        return None, "N/A (did not exist)"

    if use_ticker in PROXY_SIMULATORS:
        return PROXY_SIMULATORS[use_ticker](start, end)

    # Fetch actual prices
    prices = get_price_data(use_ticker, start, end)

    if prices is None or len(prices) < 10:
        print(f"  Warning: No data for {use_ticker} ({name})")
        return None, f"No data ({use_ticker})"

    # Convert JPY to USD if needed
    source = use_ticker if use_ticker != ticker else ticker
    if is_jpy and use_ticker == ticker and fx_rate is not None:
        # Align dates
        common_dates = prices.index.intersection(fx_rate.index)
        if len(common_dates) > 0:
            prices = prices.loc[common_dates] * fx_rate.loc[common_dates]
            source = f"{ticker} (JPY→USD)"
    elif is_jpy and use_ticker == ticker and fx_rate is None:
        rate = FX_FALLBACK_RATES.get(period_key, FX_FALLBACK_DEFAULT)
        print(f"  Warning: No FX data for {ticker}, using fallback rate {rate} JPY/USD for {period_key} period")
        prices = prices / rate
        source = f"{ticker} (est. JPY→USD @{rate:.0f})"

    return prices, source


def calc_drawdown_stats(prices: pd.Series) -> dict:
    """Calculate drawdown statistics for a price series."""
    if prices is None or len(prices) < 2:
        return {"max_drawdown": 0, "peak_date": None, "trough_date": None,
                "recovery_date": None, "total_return": 0}

    norm = normalize(prices, base=100)

    # Running maximum
    running_max = norm.cummax()

    # Drawdown series
    drawdown = (norm - running_max) / running_max

    # Max drawdown
    max_dd = drawdown.min()
    trough_idx = drawdown.idxmin()

    # Find peak before trough
    peak_idx = norm.loc[:trough_idx].idxmax()

    # Find recovery (first time price returns to peak level after trough)
    peak_val = running_max.loc[trough_idx]
    post_trough = norm.loc[trough_idx:]
    recovered = post_trough[post_trough >= peak_val]
    recovery_date = recovered.index[0] if len(recovered) > 0 else None

    total_return = (norm.iloc[-1] / norm.iloc[0]) - 1

    return {
        "max_drawdown": max_dd * 100,  # as percentage
        "peak_date": peak_idx,
        "trough_date": trough_idx,
        "recovery_date": recovery_date,
        "total_return": total_return * 100,
    }


# ── Main backtest ─────────────────────────────────────────────────────

def run_backtest(portfolio: list = None, periods: list = None):
    if portfolio is None:
        portfolio = PORTFOLIO
    if periods is None:
        periods = list(DRAWDOWNS.keys())

    results = {}

    for period_key in periods:
        period = DRAWDOWNS[period_key]
        print(f"\n{'='*60}")
        print(f"Processing: {period['label']}")
        print(f"Period: {period['start']} to {period['end']}")
        print(f"{'='*60}")

        start, end = period["start"], period["end"]

        # Fetch FX rate for JPY conversion
        print("  Fetching JPY/USD exchange rate...")
        fx_rate = get_fx_rate(start, end)

        # Fetch S&P 500 benchmark
        print("  Fetching S&P 500 benchmark...")
        sp500_prices = get_price_data("SPY", start, end)
        sp500_stats = calc_drawdown_stats(sp500_prices)

        security_results = []
        all_weighted_series = []

        for name, ticker, weight, asset_class, proxy_map in portfolio:
            print(f"  Fetching {name} ({ticker})...")
            prices, source = get_security_prices(
                name, ticker, proxy_map, period_key, start, end, fx_rate
            )

            stats = calc_drawdown_stats(prices)
            stats["name"] = name
            stats["ticker"] = ticker
            stats["weight"] = weight
            stats["asset_class"] = asset_class
            stats["source"] = source

            if prices is not None and len(prices) > 1:
                norm = normalize(prices)
                all_weighted_series.append(norm * weight)

            security_results.append(stats)

        # Combine all series: align dates with ffill only (no bfill to avoid future data leakage)
        if all_weighted_series:
            combined = pd.DataFrame({f"s{i}": s for i, s in enumerate(all_weighted_series)})
            combined = combined.ffill()
            portfolio_series = combined.sum(axis=1)
        else:
            portfolio_series = None

        # Calculate portfolio-level stats
        portfolio_stats = calc_drawdown_stats(portfolio_series)

        results[period_key] = {
            "period": period,
            "securities": security_results,
            "portfolio_series": portfolio_series,
            "portfolio_stats": portfolio_stats,
            "sp500_prices": sp500_prices,
            "sp500_stats": sp500_stats,
        }

        # Print summary
        print(f"\n  Portfolio Max Drawdown: {portfolio_stats['max_drawdown']:.1f}%")
        print(f"  Portfolio Total Return: {portfolio_stats['total_return']:.1f}%")
        print(f"  S&P 500 Max Drawdown:   {sp500_stats['max_drawdown']:.1f}%")
        print(f"  S&P 500 Total Return:   {sp500_stats['total_return']:.1f}%")

    return results


# ── HTML Report Generation ────────────────────────────────────────────

def generate_html_report(results: dict, output_path: str):
    """Generate interactive HTML dashboard with Plotly."""

    figs = []

    for period_key, data in results.items():
        period = data["period"]
        portfolio_series = data["portfolio_series"]
        sp500_prices = data["sp500_prices"]
        portfolio_stats = data["portfolio_stats"]
        sp500_stats = data["sp500_stats"]
        securities = data["securities"]

        # ── Chart 1: Portfolio vs S&P 500 ──
        fig = go.Figure()

        if portfolio_series is not None:
            norm_portfolio = portfolio_series / portfolio_series.iloc[0] * 100
            fig.add_trace(go.Scatter(
                x=[d.strftime("%Y-%m-%d") for d in norm_portfolio.index],
                y=norm_portfolio.values,
                name="Your Portfolio",
                line=dict(color="#2563eb", width=3),
            ))

        if sp500_prices is not None:
            norm_sp = sp500_prices / sp500_prices.iloc[0] * 100
            fig.add_trace(go.Scatter(
                x=[d.strftime("%Y-%m-%d") for d in norm_sp.index],
                y=norm_sp.values,
                name="S&P 500 (SPY)",
                line=dict(color="#dc2626", width=2, dash="dash"),
            ))

        fig.add_hline(y=100, line_dash="dot", line_color="gray", opacity=0.5)

        fig.update_layout(
            title=dict(text=f"{period['label']}: Portfolio vs S&P 500", font_size=20),
            yaxis_title="Indexed Value (Start = 100)",
            xaxis_title="Date",
            template="plotly_white",
            height=500,
            legend=dict(x=0.02, y=0.02, bgcolor="rgba(255,255,255,0.8)"),
            annotations=[
                dict(
                    x=0.98, y=0.98, xref="paper", yref="paper",
                    text=(f"Portfolio Max DD: {portfolio_stats['max_drawdown']:.1f}% | "
                          f"S&P 500 Max DD: {sp500_stats['max_drawdown']:.1f}%"),
                    showarrow=False, font=dict(size=13),
                    bgcolor="rgba(255,255,255,0.9)", bordercolor="gray",
                    xanchor="right", yanchor="top",
                )
            ]
        )

        figs.append(fig)

    # ── Summary table ──
    summary_rows = []
    for period_key, data in results.items():
        period = data["period"]
        ps = data["portfolio_stats"]
        ss = data["sp500_stats"]
        recovery = "N/A"
        if ps.get("recovery_date") and ps.get("trough_date"):
            days = (ps["recovery_date"] - ps["trough_date"]).days
            recovery = f"{days} days"
        summary_rows.append({
            "Crisis": period["label"],
            "Period": f"{period['start']} to {period['end']}",
            "Portfolio Max DD": f"{ps['max_drawdown']:.1f}%",
            "S&P 500 Max DD": f"{ss['max_drawdown']:.1f}%",
            "DD Reduction": f"{abs(ss['max_drawdown']) - abs(ps['max_drawdown']):.1f}pp better",
            "Portfolio Total Return": f"{ps['total_return']:.1f}%",
            "S&P 500 Total Return": f"{ss['total_return']:.1f}%",
            "Recovery Time": recovery,
        })

    # ── Per-security table for each period ──
    security_tables_html = ""
    for period_key, data in results.items():
        period = data["period"]
        secs = sorted(data["securities"], key=lambda s: s["max_drawdown"])
        rows_html = ""
        for s in secs:
            color = dd_color(s["max_drawdown"])
            rows_html += f"""
            <tr>
                <td>{s['name']}</td>
                <td>{s['asset_class']}</td>
                <td>{s['weight']*100:.1f}%</td>
                <td style="color:{color};font-weight:bold">{s['max_drawdown']:.1f}%</td>
                <td>{s['total_return']:.1f}%</td>
                <td style="font-size:0.85em;color:#666">{s['source']}</td>
            </tr>"""

        security_tables_html += f"""
        <h3 style="margin-top:2em">{period['label']} — Per-Security Drawdowns</h3>
        <table class="sec-table">
            <thead>
                <tr>
                    <th>Security</th><th>Asset Class</th><th>Weight</th>
                    <th>Max Drawdown</th><th>Total Return</th><th>Data Source</th>
                </tr>
            </thead>
            <tbody>{rows_html}</tbody>
        </table>"""

    # ── Asset class contribution analysis ──
    asset_class_html = ""
    for period_key, data in results.items():
        period = data["period"]
        secs = data["securities"]
        ac_groups = group_by_asset_class(secs)

        rows_html = ""
        for ac, vals in sorted(ac_groups.items(), key=lambda x: x[1]["weighted_dd"]):
            avg_dd = vals["weighted_dd"] / vals["weight"] if vals["weight"] > 0 else 0
            color = dd_color(avg_dd)
            rows_html += f"""
            <tr>
                <td>{ac}</td>
                <td>{vals['weight']*100:.1f}%</td>
                <td style="color:{color};font-weight:bold">{avg_dd:.1f}%</td>
                <td>{vals['weighted_dd']:.2f}%</td>
            </tr>"""

        asset_class_html += f"""
        <h3 style="margin-top:2em">{period['label']} — Asset Class Contribution</h3>
        <table class="sec-table">
            <thead>
                <tr>
                    <th>Asset Class</th><th>Portfolio Weight</th>
                    <th>Avg Max Drawdown</th><th>Weighted DD Contribution</th>
                </tr>
            </thead>
            <tbody>{rows_html}</tbody>
        </table>"""

    # ── Build HTML ──
    summary_table_html = """
    <table class="summary-table">
        <thead>
            <tr>
                <th>Crisis</th><th>Period</th><th>Portfolio Max DD</th>
                <th>S&P 500 Max DD</th><th>DD Reduction</th>
                <th>Portfolio Return</th><th>S&P 500 Return</th><th>Recovery</th>
            </tr>
        </thead>
        <tbody>"""
    for row in summary_rows:
        summary_table_html += f"""
            <tr>
                <td><strong>{row['Crisis']}</strong></td>
                <td>{row['Period']}</td>
                <td style="color:#2563eb;font-weight:bold">{row['Portfolio Max DD']}</td>
                <td style="color:#dc2626">{row['S&P 500 Max DD']}</td>
                <td style="color:#16a34a">{row['DD Reduction']}</td>
                <td>{row['Portfolio Total Return']}</td>
                <td>{row['S&P 500 Total Return']}</td>
                <td>{row['Recovery Time']}</td>
            </tr>"""
    summary_table_html += "</tbody></table>"

    chart_divs = ""
    chart_js = ""
    for i, fig in enumerate(figs):
        div_id = f"chart_{i}"
        chart_divs += f'<div id="{div_id}" style="margin-bottom:2em"></div>\n'
        chart_js += f"Plotly.newPlot('{div_id}', {json.dumps(fig.to_dict()['data'], cls=PlotlyEncoder)}, {json.dumps(fig.to_dict()['layout'], cls=PlotlyEncoder)});\n"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Portfolio Drawdown Backtest</title>
    <script src="https://cdn.plot.ly/plotly-2.35.0.min.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                max-width: 1200px; margin: 0 auto; padding: 2em; background: #fafafa; color: #1a1a1a; }}
        h1 {{ font-size: 2em; margin-bottom: 0.3em; }}
        h2 {{ font-size: 1.4em; margin-top: 2em; margin-bottom: 0.5em; color: #333; }}
        h3 {{ font-size: 1.15em; color: #555; }}
        .subtitle {{ color: #666; margin-bottom: 2em; }}
        .summary-table, .sec-table {{ width: 100%; border-collapse: collapse; margin: 1em 0; font-size: 0.9em; }}
        .summary-table th, .sec-table th {{ background: #1e293b; color: white; padding: 10px 12px; text-align: left; }}
        .summary-table td, .sec-table td {{ padding: 8px 12px; border-bottom: 1px solid #e2e8f0; }}
        .summary-table tr:hover, .sec-table tr:hover {{ background: #f1f5f9; }}
        .note {{ background: #fffbeb; border-left: 4px solid #f59e0b; padding: 1em; margin: 1em 0; font-size: 0.9em; }}
        .insight {{ background: #f0fdf4; border-left: 4px solid #22c55e; padding: 1em; margin: 1em 0; }}
    </style>
</head>
<body>
    <h1>Portfolio Drawdown Backtest</h1>
    <p class="subtitle">How would your current allocation have performed during major market crises?</p>

    <div class="note">
        <strong>Methodology:</strong> Current portfolio weights applied to historical prices.
        Proxies used for securities that didn't exist during earlier periods (noted in tables).
        Japanese equity positions converted JPY→USD using historical exchange rates.
    </div>

    <h2>Summary</h2>
    {summary_table_html}

    <h2>Performance Charts</h2>
    {chart_divs}

    <h2>Per-Security Analysis</h2>
    {security_tables_html}

    <h2>Asset Class Contribution to Drawdown</h2>
    {asset_class_html}

    <p style="margin-top:3em;color:#999;font-size:0.85em">
        Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} | Data via Yahoo Finance
    </p>

    <script>
    {chart_js}
    </script>
</body>
</html>"""

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write(html)
    print(f"\nHTML report saved to: {output_path}")


class PlotlyEncoder(json.JSONEncoder):
    """Handle numpy/pandas types in JSON serialization."""
    def default(self, obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, pd.Timestamp):
            return obj.isoformat()
        if isinstance(obj, (datetime,)):
            return obj.isoformat()
        return super().default(obj)


# ── Markdown Report ───────────────────────────────────────────────────

def generate_markdown_report(results: dict, output_path: str, portfolio: list = None):
    """Generate Obsidian-compatible markdown summary."""

    lines = [
        "# Portfolio Drawdown Backtest",
        "",
        f"*Generated {datetime.now().strftime('%Y-%m-%d')}*",
        "",
        "Backtested current portfolio allocation against three major market drawdowns.",
        "Proxies used for securities that didn't exist during earlier periods.",
        "",
        "## Summary",
        "",
        "| Crisis | Portfolio Max DD | S&P 500 Max DD | DD Reduction | Portfolio Return | S&P 500 Return |",
        "|--------|-----------------|----------------|-------------|-----------------|---------------|",
    ]

    for period_key, data in results.items():
        period = data["period"]
        ps = data["portfolio_stats"]
        ss = data["sp500_stats"]
        reduction = abs(ss["max_drawdown"]) - abs(ps["max_drawdown"])
        lines.append(
            f"| {period['label']} | {ps['max_drawdown']:.1f}% | {ss['max_drawdown']:.1f}% | "
            f"{reduction:.1f}pp better | {ps['total_return']:.1f}% | {ss['total_return']:.1f}% |"
        )

    lines += ["", "## Key Insights", ""]

    # Generate insights
    for period_key, data in results.items():
        period = data["period"]
        ps = data["portfolio_stats"]
        ss = data["sp500_stats"]
        secs = data["securities"]

        lines.append(f"### {period['label']}")
        lines.append("")

        reduction = abs(ss["max_drawdown"]) - abs(ps["max_drawdown"])
        lines.append(f"- **Drawdown reduction**: {reduction:.1f} percentage points less than S&P 500")

        # Best and worst performers
        valid_secs = [s for s in secs if s["max_drawdown"] != 0]
        if valid_secs:
            best = max(valid_secs, key=lambda s: s["max_drawdown"])
            worst = min(valid_secs, key=lambda s: s["max_drawdown"])
            lines.append(f"- **Best performer**: {best['name']} ({best['max_drawdown']:.1f}% max DD)")
            lines.append(f"- **Worst performer**: {worst['name']} ({worst['max_drawdown']:.1f}% max DD)")

        # Asset classes that helped
        ac_groups = group_by_asset_class(secs)
        ac_avg_dds = {ac: vals["weighted_dd"] / vals["weight"] if vals["weight"] > 0 else 0
                      for ac, vals in ac_groups.items()}
        best_ac = max(ac_avg_dds.items(), key=lambda x: x[1])
        worst_ac = min(ac_avg_dds.items(), key=lambda x: x[1])
        lines.append(f"- **Best asset class**: {best_ac[0]} (avg {best_ac[1]:.1f}% DD)")
        lines.append(f"- **Worst asset class**: {worst_ac[0]} (avg {worst_ac[1]:.1f}% DD)")
        lines.append("")

    # Dynamic resilience assessment based on actual portfolio
    ac_weights = {}
    if portfolio:
        for name, ticker, weight, asset_class, _ in portfolio:
            ac_weights[asset_class] = ac_weights.get(asset_class, 0) + weight
    else:
        # Derive from first period's securities
        first_period = next(iter(results.values()))
        for s in first_period["securities"]:
            ac_weights[s["asset_class"]] = ac_weights.get(s["asset_class"], 0) + s["weight"]

    sorted_acs = sorted(ac_weights.items(), key=lambda x: -x[1])

    lines += [
        "## Portfolio Resilience Assessment",
        "",
        "Portfolio allocation by asset class:",
        "",
    ]
    for ac, weight in sorted_acs:
        lines.append(f"- **{ac}**: {weight*100:.1f}%")

    lines += [
        "",
        "The portfolio's resilience during drawdowns depends on diversification across "
        "asset classes and geographies. See the per-period analysis above for how each "
        "asset class performed during specific crises.",
        "",
        "---",
        f"*See interactive HTML report for detailed charts and per-security analysis.*",
    ]

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write("\n".join(lines))
    print(f"Markdown report saved to: {output_path}")


# ── Data export ───────────────────────────────────────────────────────

def write_data_json(results: dict, output_path: str):
    """Write raw backtest results to JSON for downstream consumption."""
    export = {}
    for period_key, data in results.items():
        period = data["period"]
        ps = data["portfolio_stats"]
        ss = data["sp500_stats"]

        export[period_key] = {
            "period": period,
            "portfolio_stats": {
                "max_drawdown": ps["max_drawdown"],
                "total_return": ps["total_return"],
                "peak_date": ps["peak_date"].isoformat() if ps.get("peak_date") else None,
                "trough_date": ps["trough_date"].isoformat() if ps.get("trough_date") else None,
                "recovery_date": ps["recovery_date"].isoformat() if ps.get("recovery_date") else None,
            },
            "sp500_stats": {
                "max_drawdown": ss["max_drawdown"],
                "total_return": ss["total_return"],
                "peak_date": ss["peak_date"].isoformat() if ss.get("peak_date") else None,
                "trough_date": ss["trough_date"].isoformat() if ss.get("trough_date") else None,
                "recovery_date": ss["recovery_date"].isoformat() if ss.get("recovery_date") else None,
            },
            "securities": [
                {
                    "name": s["name"],
                    "ticker": s["ticker"],
                    "weight": s["weight"],
                    "asset_class": s["asset_class"],
                    "source": s["source"],
                    "max_drawdown": s["max_drawdown"],
                    "total_return": s["total_return"],
                }
                for s in data["securities"]
            ],
        }

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(export, f, indent=2, default=str)
    print(f"Data JSON saved to: {output_path}")


# ── Entry point ───────────────────────────────────────────────────────

def main(argv: list = None):
    """Main entry point with CLI argument support."""
    args = parse_args(argv)

    # Load portfolio
    if args.portfolio_json:
        portfolio = load_portfolio_from_json(args.portfolio_json)
    else:
        portfolio = PORTFOLIO

    # Parse periods
    periods = args.periods.split(",")

    print("Starting Portfolio Drawdown Backtest...")
    print(f"Portfolio has {len(portfolio)} positions")
    print(f"Weights sum to {sum(w for _, _, w, _, _ in portfolio)*100:.1f}%")

    results = run_backtest(portfolio=portfolio, periods=periods)

    # Determine output paths
    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        output_dir = Path(f"./{timestamp}-portfolio-backtest")
    output_dir.mkdir(parents=True, exist_ok=True)
    html_path = str(output_dir / f"{timestamp}-dashboard.html")
    md_path = str(output_dir / f"{timestamp}-summary.md")
    data_path = str(output_dir / f"{timestamp}-data.json")

    if not args.no_html:
        generate_html_report(results, html_path)

    generate_markdown_report(results, md_path, portfolio=portfolio)

    write_data_json(results, data_path)

    print(f"\nDone! Reports saved to {output_dir}/")


if __name__ == "__main__":
    main()
