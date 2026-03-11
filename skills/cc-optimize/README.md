# CC Optimize

Analyzes your credit card portfolio to find spending misallocations, check whether annual fees are justified, and generate an optimization dashboard — all from your actual transaction data.

## Usage

```
/cc-optimize
/cc-optimize --months 12 --skip-gmail
```

| Argument | Default | Description |
|----------|---------|-------------|
| `--months N` | 6 | Lookback period for transaction analysis |
| `--skip-dashboard` | false | Skip HTML dashboard generation |
| `--skip-gmail` | false | Skip Gmail verification of fees/credits |

## Prerequisites

- **Hiro MCP server** connected to Claude with linked financial accounts
- **[gog CLI](https://github.com/steipete/gogcli)** (optional) — only needed for Gmail-based fee/credit verification. Skip with `--skip-gmail` if not installed.

## What It Produces

Each run creates a timestamped folder — previous runs are never overwritten:

```
cc-optimize-YYYY-MM-DD-HHMM/
├── cc-optimize-YYYY-MM-DD-HHMM-analysis.md
├── cc-optimize-YYYY-MM-DD-HHMM-dashboard.html
└── cc-optimize-YYYY-MM-DD-HHMM-data.json
```

- **analysis.md** — The full written analysis: card-by-card breakdown, spending misallocations, fee analysis, credit/perk utilization, an optimal wallet routing guide, and ranked action items.
- **dashboard.html** — Interactive single-file HTML dashboard (no server needed). Charts for spending by card and category, misallocation visualization, fee analysis, and the wallet guide.
- **data.json** — Raw data snapshot of all analysis results. Useful for diffing between runs to see how your optimization is progressing.

## How to Read the Results

**Misallocations** — The most actionable section. A misallocation means you're charging a spending category (e.g., dining) to a card that earns a lower reward rate than another card you already have. The table shows the annual dollar value you're leaving on the table for each one.

**Wallet Routing Guide** — The cheat sheet: for each spending category, which card to use and what rate you'll earn. Put this somewhere handy (phone notes, wallet insert) for daily use.

**Card Statuses (Keep / Downgrade / Cancel)** — Each fee-bearing card gets a verdict based on whether the rewards and credits it earns exceed its annual fee:
- **Keep** — Net positive value; the card is paying for itself.
- **Downgrade** — Net negative value, but a no-annual-fee version exists. You keep the credit history.
- **Cancel** — Net negative value with no worthwhile downgrade path.
- **Evaluate** — Close call or missing data; needs a judgment call.

**Credit Utilization** — For premium cards, shows which statement credits and perks you're actually claiming vs. leaving unused. Unclaimed credits are money left on the table.

## How It Works

The skill runs 6 phases automatically: (1) research current points valuations and card reward structures from the web, (2) discover all your credit cards via Hiro and optionally cross-reference Gmail for fee/credit history, (3) pull and categorize all transactions for the lookback period, detecting how you redeem points in each program, (4) run optimization analysis — earning rates, misallocations, fee justification, and optimal routing, (5) write the analysis document, and (6) generate and open the interactive dashboard.
