---
name: cc-optimize
description: Analyzes credit card portfolio using Hiro transaction data and Gmail, identifies savings opportunities, and produces a markdown analysis + interactive HTML dashboard.
argument-hint: "[--months N] [--skip-dashboard] [--skip-gmail]"
allowed-tools: Bash(cat *), Bash(gog *), Bash(open *), Bash(mkdir *), Bash(cp *), Read, Write, Edit, Glob, Grep, WebSearch, AskUserQuestion, mcp__hiro__list_transactions, mcp__hiro__list_accounts, mcp__hiro__list_categories, mcp__hiro__get_account
---

# CC Optimize

Analyze credit card portfolio, identify savings opportunities, and generate an interactive dashboard.

## Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--months N` | 6 | Lookback period for transaction analysis |
| `--skip-dashboard` | false | Skip HTML dashboard generation |
| `--skip-gmail` | false | Skip Gmail verification of fees/credits |

## Output Structure

Each run creates a timestamped folder — never overwrites previous runs:

```
cc-optimize-YYYY-MM-DD-HHMM/
├── cc-optimize-YYYY-MM-DD-HHMM-analysis.md      # Full analysis document
├── cc-optimize-YYYY-MM-DD-HHMM-dashboard.html   # Interactive dashboard
└── cc-optimize-YYYY-MM-DD-HHMM-data.json        # Raw data snapshot
```

## Prerequisites

- **Hiro MCP server** connected to Claude with linked financial accounts
- **[gog CLI](https://github.com/steipete/gogcli)** (optional) — only needed for Gmail-based fee/credit verification. Skip with `--skip-gmail` if not installed.

## Workflow

Execute these 6 phases sequentially. Each phase feeds the next. Do NOT ask the user for guidance between phases — proceed autonomously using the instructions below.

### Phase 1: Research — Current Card Data

**Goal:** Get current points valuations and card reward structures from the web.

1. **Points valuations by redemption method**: Web search for "credit card points valuations [current year]" from sources like The Points Guy (TPG), NerdWallet, Bankrate. For each program, research **3-4 redemption methods with their cpp values** (e.g., transfer to airline/hotel partners, travel portal, statement credit, Pay with Points). Extract per-method cpp for:
   - Amex Membership Rewards (MR)
   - Chase Ultimate Rewards (UR)
   - Capital One Miles
   - Hilton Honors
   - United MileagePlus
   - Any other programs discovered in Phase 2

2. **Card reward structures**: After discovering cards in Phase 2, search "[card name] rewards rates [current year]" for each card to get:
   - Category multipliers (dining, travel, groceries, gas, streaming, etc.)
   - Annual fee
   - Credits and perks (with dollar values)
   - Foreign transaction fee status
   - Sign-up bonus status (if relevant)

Store all research results for use in later phases. Note sources for citation in the final report.

### Phase 2: Inventory — Discover All Credit Cards

1. Pull all accounts from Hiro using `mcp__hiro__list_accounts`, filter to credit cards
2. For each card, extract: name, institution, credit limit, current balance
3. If `--skip-gmail` is NOT set, cross-reference with Gmail for annual fee charges:
   ```bash
   gog gmail search 'subject:"annual fee" OR subject:"annual membership" OR subject:"yearly fee"' --max 100 --account YOUR_GMAIL_ACCOUNT
   ```
   Also search for:
   ```bash
   gog gmail search 'subject:"statement credit" OR subject:"benefit" OR subject:"perk"' --max 100 --account YOUR_GMAIL_ACCOUNT
   ```
4. Match each discovered card to its reward structure from Phase 1 web research
5. For any card that can't be identified, ask the user via `AskUserQuestion`

### Phase 3: Spending Analysis — Where Money Goes on Which Card

1. Calculate the date range based on `--months` argument (default 6 months back from today)
2. Pull ALL transactions for the period using `mcp__hiro__list_transactions` with date range
   - Paginate through ALL results using cursor pagination — do not stop at first page
   - Filter to credit card accounts only
3. Group transactions by:
   - **Card** (account_id) — total spend per card
   - **Category** — spend by category per card
   - **Month** — monthly breakdown per card
4. Identify top spending categories across all cards:
   - Travel (flights, hotels, car rental)
   - Dining (restaurants, food delivery)
   - Groceries (supermarkets)
   - Gas/Transit
   - Online shopping / Amazon
   - Streaming/subscriptions
   - General/other
5. Flag foreign transactions (for FX fee analysis) — look for transactions with non-USD indicators or known foreign merchants
6. Calculate annualized spending rates from the period analyzed

#### 3a. Detect Redemption Methods

Scan transactions and Gmail for signals of how the user redeems points in each rewards program. This determines which cpp value from Phase 1 to use.

**Transactions (Hiro)** — scan for credits/negative amounts indicating redemptions:
- Statement credits from issuer: merchant names like "AMEX REWARD", "CHASE CASHBACK REDEMPTION", "REWARDS REDEMPTION"
- Travel portal charges: "AMEX TRAVEL", "CHASE TRAVEL", "CAPITAL ONE TRAVEL"
- Pay with Points partial credits on retail purchases

**Gmail (if not skipped)** — search for redemption-related emails:
```bash
gog gmail search 'subject:"points transfer" OR subject:"miles transfer" OR subject:"transfer confirmation" OR from:airline' --max 50
gog gmail search 'subject:"travel booking" OR from:"amextravel" OR from:"chase travel"' --max 50
gog gmail search 'subject:"rewards redemption" OR subject:"cashback" OR subject:"statement credit" from:amex OR from:chase' --max 50
```

**Detection logic per program:**

| Signal | Inferred method |
|--------|----------------|
| Transfer confirmation emails to airline/hotel partners | Partner transfer |
| Travel portal booking charges or emails | Travel portal |
| Statement credit transactions | Statement credit |
| No signals found | Unknown — ask user |

Record: program, detected method (or "unknown"), evidence summary.

#### 3b. Confirm Redemption Methods with User

After detection, present findings and ask the user to confirm or correct — **one `AskUserQuestion` for all programs**. Pre-fill detected methods and only require input for unknowns. Skip programs with only one meaningful redemption option (pure cash-back cards).

Example prompt:
```
Based on your transactions and emails, here's how you appear to redeem points.
Please confirm or correct — this affects how we value your rewards.

**Amex MR** — used by: Amex Gold, Amex Platinum
  Detected: Transfer to airline partners (~2.0 cpp)
  Evidence: Found 3 transfer confirmation emails to Delta SkyMiles
  → Is this right? Other options: Travel portal (~1.0 cpp), Statement credit (~0.6 cpp)

**Chase UR** — used by: Chase Sapphire Reserve
  Detected: Could not determine
  Options:
  1. Transfer to airline/hotel partners (~1.8 cpp)
  2. Chase Travel portal (~1.5 cpp via CSR)
  3. Statement credit (~1.0 cpp)

Reply with corrections or confirmations, e.g. "MR looks right, UR: 2"
```

Default to detected method (or highest-value if unknown) if user doesn't respond clearly.

### Phase 4: Optimization Analysis

Using data from Phases 1-3, perform the following analyses:

#### 4a. Earning Rate Calculation
For each card, calculate the effective earning rate using actual spending patterns:
- Apply the card's category multipliers to actual category spending
- Account for monthly/quarterly caps on bonus categories
- Account for tiered rates where applicable
- Convert points earned to dollar value using the redemption-specific cpp determined in Phase 3
- Calculate: effective earning rate = (total points value earned) / (total spend)

#### 4b. Spending Misallocations
For each major spending category:
- Identify which card it's currently being charged to
- Identify which card in the portfolio would be optimal for that category
- Calculate the annual dollar difference if spending were routed optimally
- Rank misallocations by annual value lost

#### 4c. Fee Analysis
For each fee-bearing card:
- Calculate total value received (rewards earned + credits used + perks valued)
- Subtract annual fee
- Determine net value (positive = keep, negative = evaluate)
- Calculate break-even spending level

#### 4d. Credit/Perk Utilization (if Gmail not skipped)
For premium cards, check Gmail for evidence of credit claims:
- Entertainment credits (Disney+, Hulu, etc.)
- Uber/Lyft credits
- CLEAR membership
- Hotel credits (Hilton, Marriott)
- Airline incidentals
- Walmart+ / Instacart+
- Dining credits
- Saks / other retail credits

Track: credit name, amount available, amount claimed (from Gmail evidence), amount unclaimed

#### 4e. Recommendations
Assign each card a status with rationale:
- **Keep** — Positive net value, well-utilized
- **Downgrade** — Negative net value but has a no-fee version
- **Cancel** — Negative net value, no downgrade path, not worth the fee
- **Evaluate** — Need more info or close call

#### 4f. Optimal Routing (Wallet Guide)
Build the definitive category → card → rate mapping:
```
Category          | Best Card              | Rate
Dining            | Amex Gold              | 4x MR (4.8 cpp)
Groceries         | Amex Gold              | 4x MR (up to $25k/yr)
Travel (flights)  | Chase Sapphire Reserve | 3x UR (4.5 cpp)
...
```

#### 4g. Action Items
Generate a ranked list of changes by annual value:
- Each item: description, annual value, difficulty (Easy/Medium/Hard)
- Easy = just change which card you use
- Medium = requires a phone call or app change
- Hard = requires opening/closing accounts

### Phase 5: Write Analysis Document

Create the timestamped output folder and write `$STAMP-analysis.md`:

```bash
STAMP="cc-optimize-$(date +%Y-%m-%d-%H%M)"
OUTPUT_DIR="./$STAMP"
mkdir -p "$OUTPUT_DIR"
```

**`$STAMP-analysis.md` sections:**

1. **Overview** — Date, analysis period, total spend across all cards, total annual fees, estimated annual savings opportunity
2. **Points Valuations Used** — Table of program → redemption method → cpp value with source. Include how each method was determined (auto-detected from transactions/email vs. user-specified) and list alternative redemption options not chosen with their cpp values.
3. **Card-by-Card Breakdown** — Table: Card Name | Annual Fee | Period Spend | Best Earning Rate | Effective Earning Rate | Status (Keep/Downgrade/Cancel/Evaluate)
4. **Cards to Downgrade/Cancel** — For each: card name, current fee, savings from action, rationale, downgrade target (if applicable)
5. **Cards to Evaluate** — For each: what needs checking and why it's a close call
6. **Top 5 Spending Misallocations** — Category | Current Card | Current Rate | Optimal Card | Optimal Rate | Annual Value Difference
7. **Premium Card Credit Utilization** — Card | Credit | Available | Claimed | Unclaimed | Annual Value at Risk
8. **Optimal Wallet Routing Guide** — The definitive category → card table for daily use
9. **Action Items** — Ranked by annual value with difficulty ratings

### Phase 6: Generate Dashboard (unless `--skip-dashboard`)

1. Read the dashboard template from this skill's directory:
   ```
   dashboard-template.html
   ```
2. Build the `DATA` JSON object containing all analysis results structured for the dashboard
3. Replace `/* __DATA_PLACEHOLDER__ */` in the template with the actual JSON data
4. Save as `$STAMP-dashboard.html` in the output folder
5. Open in browser:
   ```bash
   open "$OUTPUT_DIR/$STAMP-dashboard.html"
   ```

Also save `$STAMP-data.json` in the output folder for future diffing between runs.

## DATA JSON Structure

The dashboard template expects this structure:

```json
{
  "generated": "2026-03-07T14:30:00",
  "period": { "start": "2025-09-07", "end": "2026-03-07", "months": 6 },
  "summary": {
    "totalSpend": 45000,
    "totalFees": 1250,
    "totalSavings": 890,
    "cardCount": 5
  },
  "pointsValuations": [
    {
      "program": "Amex MR",
      "cpp": 2.0,
      "redemptionMethod": "Transfer to airline/hotel partners",
      "detectedFrom": "Gmail: 3 transfer confirmations to Delta SkyMiles",
      "source": "TPG Mar 2026",
      "allOptions": [
        { "method": "Transfer to airline/hotel partners", "cpp": 2.0 },
        { "method": "Amex Travel portal", "cpp": 1.0 },
        { "method": "Statement credit", "cpp": 0.6 }
      ]
    }
  ],
  "cards": [
    {
      "name": "Amex Gold",
      "institution": "American Express",
      "annualFee": 250,
      "spend": 18000,
      "effectiveRate": 0.038,
      "bestRate": 0.048,
      "status": "keep",
      "statusReason": "Strong dining/grocery rewards offset fee",
      "creditLimit": 25000,
      "categories": [
        { "name": "Dining", "spend": 8000, "rate": 0.04, "pointsEarned": 32000 }
      ]
    }
  ],
  "misallocations": [
    {
      "category": "Dining",
      "currentCard": "Chase Freedom",
      "currentRate": 0.01,
      "optimalCard": "Amex Gold",
      "optimalRate": 0.04,
      "annualSpend": 6000,
      "annualLoss": 180
    }
  ],
  "credits": [
    {
      "card": "Amex Platinum",
      "credit": "Uber Credit",
      "available": 200,
      "claimed": 150,
      "unclaimed": 50
    }
  ],
  "walletGuide": [
    {
      "category": "Dining",
      "card": "Amex Gold",
      "rate": "4x MR",
      "effectiveCpp": 0.048,
      "notes": "Up to $25k/yr"
    }
  ],
  "actionItems": [
    {
      "action": "Move dining spend to Amex Gold",
      "annualValue": 180,
      "difficulty": "Easy",
      "details": "Currently split across Chase Freedom and Citi Double Cash"
    }
  ],
  "monthlySpend": [
    { "month": "2025-10", "total": 7500, "byCard": { "Amex Gold": 3000, "Chase Sapphire": 2500, "Other": 2000 } }
  ]
}
```

## Important Notes

- **Don't ask for workflow guidance** — proceed through all 6 phases autonomously without asking "what should I do next?" or "how should I analyze this?"
- **DO ask about unidentifiable cards** — if you can't determine a card's reward structure from web search (e.g., obscure card, ambiguous name from Hiro), ask the user via `AskUserQuestion` what card it is, its reward rates, and annual fee. Getting this right matters more than speed.
- **Paginate all Hiro API calls** — always check for cursor/next and fetch all pages
- **Use current web data** — do not rely on embedded knowledge for points valuations or card benefits
- **Be precise with numbers** — never round unless displaying summaries. Keep full precision in the data JSON
- **Detect redemption methods before asking** — scan transactions for reward credits and Gmail for transfer/booking confirmations. Only ask the user to confirm or fill gaps. Critical because cpp varies 2-3x by redemption method.
- **Cite sources** — include URLs or source names for all points valuations
