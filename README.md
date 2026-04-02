# FinAgent

**A personal AI-powered finance research assistant** — automatically fetches analyst ratings, news, financials, and geopolitical risk for your stock watchlist, synthesizes it with Claude AI, and delivers a polished report to your inbox every morning.

---

## What it does

| Section | What you get |
|---|---|
| **Analyst Ratings** | Per-firm ratings, price targets, and actions (upgrade/downgrade) scraped from StockAnalysis.com. Claude writes a consensus summary. |
| **News** | Recent headlines from Yahoo Finance, Google News, CNBC, MarketWatch, and Reuters — classified as direct, supply-chain, or macro. |
| **Financials** | 3-year revenue, margins, free cash flow, valuation multiples, debt/equity, insider transactions, short interest, and a peer comparison table — all from yfinance. |
| **Geopolitical Exposure** | Claude identifies live geopolitical risks grounded in specific recent headlines, dated and cited. |
| **Supply Chain Map** | Auto-discovered upstream/downstream relationships visualized as an interactive SVG diagram. Nodes in your watchlist are clickable. |

The report is a single self-contained HTML page hosted on GitHub Pages, updated on a schedule or on-demand.

---

## Live report

> Hosted at: `https://<your-username>.github.io/FinAgent/`

---

## Architecture

```
main.py                        CLI entry point
│
├── agents/
│   ├── orchestrator.py        Runs all agents in parallel (ThreadPoolExecutor)
│   ├── analyst_ratings_agent  Scrapes StockAnalysis.com + Claude summary
│   ├── news_agent             RSS fetch + Claude classification
│   ├── financials_agent       yfinance data + Claude analysis
│   ├── geopolitical_agent     Claude geo-risk from recent headlines
│   └── supply_chain_agent     Claude auto-discovers upstream/downstream
│
├── data_sources/
│   ├── yfinance_client        Price, financials, insiders, short data
│   ├── stockanalysis_client   Individual analyst ratings scraper
│   ├── rss_client             Yahoo, Google News, CNBC, MarketWatch, Reuters
│   └── wsj_client             WSJ headlines (+ full text with cookie)
│
├── delivery/
│   ├── digest.py              Builds email digest (subject + HTML + text)
│   ├── email_sender.py        Gmail SMTP
│   └── whatsapp_sender.py     CallMeBot WhatsApp API
│
├── templates/
│   └── report.html.j2         Jinja2 report template (tabs, dark mode, i18n)
│
└── .github/workflows/
    ├── generate_report.yml    Daily 7am SGT + on-demand trigger
    └── refresh_supply_chain   Weekly Sunday supply chain refresh
```

---

## Setup

### 1. Fork and clone

```bash
git clone https://github.com/<you>/FinAgent.git
cd FinAgent
pip install -r requirements.txt
cp .env.example .env
```

### 2. Configure your watchlist

Edit `config/stocks.json`:

```json
{
  "tickers": [
    { "symbol": "NVDA", "name": "NVIDIA", "sector": "Semiconductors" },
    { "symbol": "AAPL", "name": "Apple", "sector": "Technology" }
  ],
  "subscribers": {
    "email": ["you@example.com"],
    "whatsapp": ["+6512345678"]
  }
}
```

### 3. Set environment variables

Fill in `.env` (for local runs) and GitHub Secrets (for Actions):

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | [Get one here](https://console.anthropic.com/) |
| `SMTP_USER` | For email | Gmail address |
| `SMTP_PASSWORD` | For email | Gmail [App Password](https://myaccount.google.com/apppasswords) (requires 2FA) |
| `WHATSAPP_APIKEY` | For WhatsApp | [CallMeBot](https://www.callmebot.com/blog/free-api-whatsapp-messages/) free API key |
| `WSJ_COOKIE` | Optional | WSJ session cookie for full article text |
| `GITHUB_REPO` | Auto-set | Set by Actions as `owner/repo` |

### 4. Enable GitHub Pages

In your repo: **Settings → Pages → Source: Deploy from branch → `gh-pages` / `/ (root)`**

### 5. Add GitHub Secrets

**Settings → Secrets and variables → Actions → New repository secret** — add each variable from the table above.

### 6. Run locally

```bash
# Full report
python main.py

# Single section (faster for testing)
python main.py --section analyst

# Chinese AI summaries
python main.py --lang zh

# Preview the email without re-running
python main.py --preview-email

# Refresh supply chain relationships
python main.py --refresh-supply-chain
```

---

## Daily delivery

The workflow runs every weekday at **7:00 AM SGT** (23:00 UTC Sun–Thu). After each run, the updated report is deployed to GitHub Pages and the digest is emailed/WhatsApp'd to all subscribers.

To trigger an immediate update, open the report and click **Refresh Report** — or go to **Actions → Generate Finance Report → Run workflow**.

---

## Adding a stock

Click **+ Add Stock** in the report header. Enter the ticker symbol. The workflow triggers automatically, discovers the supply chain, generates all sections, and reloads the page when done. Your GitHub PAT is saved in the browser so you only enter it once.

---

## Report features

- **Per-stock tabs** — drag to reorder, × to hide, restore button to unhide
- **Dark mode** — toggle in the header, persisted in browser
- **Language toggle** — EN / ZH (Chinese AI summaries via `--lang zh`)
- **Archive** — every run is saved; browse history from the header dropdown
- **Sparklines** — 90-day price chart in each ticker's hero section
- **Supply chain SVG** — clickable nodes navigate to watched tickers
- **Geopolitical timeline** — each theme is dated and sourced to specific headlines

---

## Data sources

| Data | Source |
|---|---|
| Analyst ratings & price targets | StockAnalysis.com (scraped) |
| Financials, earnings, insiders, short interest | yfinance |
| Ticker news | Yahoo Finance RSS, Google News RSS |
| Market & macro news | CNBC, MarketWatch, Reuters RSS |
| Full article text | WSJ (optional, requires subscription cookie) |
| AI synthesis | Anthropic Claude (claude-sonnet-4-6) |

All sources are free except Anthropic API usage and the optional WSJ subscription.

---

## License

MIT
