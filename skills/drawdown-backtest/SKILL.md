---
name: drawdown-backtest
description: Fetches portfolio from Hiro, backtests against major market crises (dot-com, GFC, COVID), generates interactive dashboard + markdown summary.
argument-hint: "[--periods dotcom,gfc,covid] [--skip-dashboard]"
allowed-tools: Bash(python3 *), Bash(open *), Bash(mkdir *), Read, Write, Edit, Glob, mcp__hiro__list_holdings, mcp__hiro__list_accounts, mcp__hiro__list_securities, mcp__hiro__get_security, mcp__hiro__get_holding
---

# Drawdown Backtest

Fetch live portfolio from Hiro, classify holdings, backtest against major market crises, and generate an interactive dashboard + markdown summary.

## Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--periods LIST` | `dotcom,gfc,covid` | Comma-separated crisis periods to test |
| `--skip-dashboard` | false | Skip HTML dashboard generation and browser open |

## Output Structure

Each run creates a timestamped folder in the current working directory:

```
./drawdown-backtest-YYYY-MM-DD-HHMM/
├── dashboard.html    # Interactive Plotly dashboard
├── summary.md        # Markdown analysis
├── portfolio.json    # Input snapshot for reproducibility
└── data.json         # Raw results for downstream use
```

## Prerequisites

- **Hiro MCP server** connected to Claude with linked brokerage/investment accounts
- **Python 3** with dependencies: `pip3 install yfinance pandas numpy plotly pytest`

## Workflow

Execute these 6 phases sequentially and autonomously. Do NOT ask the user for guidance between phases.

### Phase 1: Fetch Portfolio from Hiro

1. Call `mcp__hiro__list_accounts` — filter to investment/brokerage accounts only
2. For each investment account, call `mcp__hiro__list_holdings` — paginate fully (check for cursor/next)
3. For each holding, call `mcp__hiro__get_security` using the security_id to get ticker, name, type
4. Calculate weights: `holding_value / total_portfolio_value`
5. Handle edge cases:
   - **Cash positions**: Exclude from backtest (weight=0)
   - **Negative cash / margin**: Note in metadata but exclude from positions
   - **Mutual funds**: Map to ETF equivalents (e.g., VITNX -> VTI, VFIAX -> VOO)
   - **Missing tickers**: Use security name to infer, or flag for manual review

Write down every holding's ticker, name, value, and weight as you go — tool results may be cleared from context later.

### Phase 2: Auto-Classify Holdings

Classify each holding into an asset class using ticker + security name. Use these patterns:

| Pattern | Asset Class |
|---------|-------------|
| SHV/BIL/SGOV, "Treasury Bill", "Money Market" | Short-term bonds |
| TLT/SPTL/VGLT, "Long Treasury" | Long-term bonds |
| TIP/LTPZ/VTIP, "TIPS", "Inflation Protected" | TIPS |
| GLD/GLDM/SGOL/IAU, "Gold" | Gold |
| DBC/PDBC/GSG, "Commodity" | Commodities |
| GUNR/XLE, "Natural Resource" | Natural resources |
| VEA/EFA/IEFA, "Intl Developed", "International Equity" | Intl developed equity |
| IGOV/BWX, "Intl Bond", "International Treasury" | Intl bonds |
| EEM/IEMG/DEM/DGS, "Emerging Market Equity" | EM equity |
| EMB/EMLC/EBND, "Emerging Market Bond" | EM bonds |
| VTI/SPY/VOO/VFIAX/VITNX, "US Equity", "Total Stock", "S&P 500" | US equity |
| Ticker ends in `.T` (8xxx.T = sogo shosha) | Japanese equity |
| BTC-USD/ETH-USD, "Bitcoin", "Ethereum" | Crypto |
| CCJ/SRUUF/URA, "Uranium" | Uranium |

For ambiguous holdings, reason about them using the security name, type, and any other available context. This is where Claude adds value over a static mapping.

### Phase 3: Build Proxy Mappings

Assign proxies per asset class per crisis period. Many securities didn't exist during earlier crises, so proxies provide historical approximations.

| Asset Class | Dot-com (2000-2003) | GFC (2007-2009) | COVID (2020) |
|-------------|---------------------|------------------|--------------|
| Short-term bonds | `_TBILL` | `_TBILL` | `_TBILL` |
| Long-term bonds | `_LT_TREASURY` | `TLT` | actual |
| TIPS | `_TIPS_PROXY` | `_TIPS_PROXY` | actual |
| Gold | `GC=F` | `GC=F` | actual or `GC=F` |
| Commodities | `_GSCI_PROXY` | `DBC` | actual |
| Natural resources | `XLE` | `XLE` | actual |
| Intl developed equity | `EFA` | `EFA` | actual |
| Intl bonds | `_INTL_BOND_PROXY` | `_INTL_BOND_PROXY` | actual |
| EM equity | `_EM_EQUITY_PROXY` | `EEM` | actual |
| EM bonds | `_EM_BOND_PROXY` | `_EM_BOND_PROXY` | actual |
| US equity | `SPY` | actual or `SPY` | actual |
| Japanese equity | actual (TSE tickers go back to 1990s) | actual | actual |
| Crypto | `_NO_DATA` | `_NO_DATA` | actual |
| Uranium | `CCJ` | `CCJ` | actual or `CCJ` |

**Rules for "actual or PROXY":** Use actual ticker if it existed during the period (check inception date from security metadata). Otherwise fall back to the proxy.

### Phase 4: Run Backtest Script

1. Assemble the portfolio JSON from Phases 1-3:
   ```json
   {
     "positions": [
       {
         "name": "SGOV (0-3M Treasury)",
         "ticker": "SGOV",
         "weight": 0.163,
         "asset_class": "Short-term bonds",
         "proxy_map": {"dotcom": "_TBILL", "gfc": "_TBILL", "covid": "_TBILL"}
       }
     ],
     "metadata": {
       "source": "hiro",
       "fetched_at": "2026-03-08T12:00:00",
       "total_value": 9350000
     }
   }
   ```

2. Create the output directory:
   ```bash
   OUTPUT_DIR="./drawdown-backtest-$(date +%Y-%m-%d-%H%M)"
   mkdir -p "$OUTPUT_DIR"
   ```

3. Write portfolio JSON:
   ```bash
   # Write the portfolio JSON to the output directory (use Write tool)
   ```

4. Parse `--periods` argument (default: `dotcom,gfc,covid`)

5. Run the backtest:
   ```bash
   python3 ${CLAUDE_SKILL_DIR}/portfolio_drawdown_backtest.py \
     --portfolio-json "$OUTPUT_DIR/portfolio.json" \
     --output-dir "$OUTPUT_DIR" \
     --periods dotcom,gfc,covid
   ```
   Use a 5-minute timeout (yfinance can be slow).

6. Verify output: check that `data.json` and `dashboard.html` exist in the output directory.

### Phase 5: Write Markdown Summary

1. Read `data.json` from the output directory
2. Write `summary.md` in the same output directory with these sections:

**Structure of summary.md:**
- **Title + date**
- **Summary table**: Crisis | Portfolio Max DD | S&P 500 Max DD | DD Reduction | Portfolio Return | S&P 500 Return
- **Key Insights per period**: Drawdown reduction, best/worst performers, best/worst asset classes
- **Portfolio Resilience Assessment**: Dynamically generated based on actual allocation weights — do NOT hardcode percentages. Calculate actual weights per asset class from the portfolio data and describe the defensive/risk characteristics based on what's actually in the portfolio.
- **Methodology Notes**:
  1. Buy-and-hold only — no rebalancing during the period
  2. Margin/leverage excluded — actual drawdowns would be slightly worse
  3. Simulated series use fixed seeds but are uncorrelated — may understate portfolio drawdown
  4. Point-in-time weights applied retroactively to historical data
  5. Proxy annotations shown per-security in the HTML dashboard tables
- **Link to HTML dashboard**

### Phase 6: Open Dashboard (unless `--skip-dashboard`)

1. Open the HTML dashboard in the default browser:
   ```bash
   open "$OUTPUT_DIR/dashboard.html"
   ```

2. Display completion summary to the user with:
   - Output directory path
   - Key numbers: portfolio max DD vs S&P 500 for each period
   - Number of positions backtested
   - Any data gaps or warnings

## Important Notes

- **Don't ask for workflow guidance** — proceed through all 6 phases autonomously
- **Paginate all Hiro API calls** — always check for cursor/next and fetch ALL pages
- **Be precise with numbers** — never round amounts in data files
- **Write down important data** — Hiro tool results may be cleared from context. Record ticker, name, value, and weight for each holding immediately after fetching.
- **Handle yfinance failures gracefully** — some tickers may fail to download. The script handles this internally, but if the entire script fails, check for missing dependencies (`pip3 install yfinance pandas numpy plotly`) and retry.
