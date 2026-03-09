# Claude Financial Skills

Personal financial skills for [Claude Code](https://claude.com/claude-code) and [Claude Desktop](https://claude.ai/download), powered by the [Hiro Finance](https://hirofinance.com) MCP server.

## Skills

| Skill | Description | Hiro MCP Tools Used |
|-------|-------------|---------------------|
| **cc-optimize** | Analyzes your credit card portfolio, identifies spending misallocations, and generates an interactive optimization dashboard | `list_accounts`, `list_transactions`, `list_categories`, `get_account` |
| **drawdown-backtest** | Backtests your portfolio against major market crises (dot-com, GFC, COVID) with interactive charts | `list_accounts`, `list_holdings`, `list_securities`, `get_security`, `get_holding` |

## Prerequisites

1. **Claude Code** or **Claude Desktop** installed
2. **Hiro account** with linked financial accounts at [hirofinance.com](https://hirofinance.com)
3. **Hiro MCP server** connected to Claude — see [Hiro MCP](https://hirofinance.com/mcp) for setup

### Optional

- **[gog CLI](https://github.com/steipete/gogcli)** — Gmail integration for cc-optimize's fee/credit verification (skip with `--skip-gmail`)
- **Python 3** with `yfinance`, `pandas`, `numpy`, `plotly` — required for drawdown-backtest

## Installation

### As a plugin (recommended)

```bash
# Install from GitHub
claude plugin install github.com/hiro-finance-inc/claude-financial-skills
```

### Manual

Clone and point Claude at the plugin directory:

```bash
git clone https://github.com/hiro-finance-inc/claude-financial-skills.git
claude --plugin-dir ./claude-financial-skills
```

Or copy individual skills into your project:

```bash
cp -r claude-financial-skills/skills/cc-optimize .claude/skills/
cp -r claude-financial-skills/skills/drawdown-backtest .claude/skills/
```

## Usage

Once installed, invoke skills from Claude Code or Claude Desktop:

```
/cc-optimize
/cc-optimize --months 12 --skip-gmail
/drawdown-backtest
/drawdown-backtest --periods gfc,covid
```

## How It Works

These skills are instruction sets (SKILL.md files) that tell Claude how to:

1. Fetch your financial data from the Hiro MCP server
2. Analyze it (spending patterns, portfolio allocations, etc.)
3. Generate reports and interactive dashboards

The Hiro MCP server provides secure, read-only access to your financial accounts. Claude does the analysis — no data is sent to third-party services beyond Anthropic's API.

## License

MIT
