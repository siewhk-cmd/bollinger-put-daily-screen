# Daily Bollinger Put-Selling Screener

This repository screens the hard-coded S&P 500 + ETF universe for two Bollinger strategies.

A candidate qualifies only when:

1. A current Strategy 1 or Strategy 2 signal exists on the latest completed U.S. trading session.
2. The ticker is historically **Effective for that exact strategy** in `stock_effectiveness.csv`.
3. SPY is **Bullish or Sideways/Transitional**, not Bearish.

The job runs at **07:30 Asia/Singapore every Tuesday-Saturday**, which is after the prior U.S. Monday-Friday market close. It sends the summary and candidate charts to Telegram. If no candidate qualifies, Telegram explicitly says:

> No stocks or ETFs fit the criteria today.

## Chart format

Qualified candidates get a 6-month OHLC chart showing:

- OHLC marks
- Upper / Middle / Lower Bollinger Bands, labelled directly at the right edge (no Bollinger legend)
- Strategy 1 or Strategy 2 signal
- Exact signal date and signal Close price
- Technical X
- **Proposed put strike as a thick horizontal line across the full chart, with the strike price printed on the chart**
- Historical classification
- SPY regime
- Earnings date / `<30D` warning

## Files

- `daily_bollinger_put_screen.py` — daily scanner
- `stock_effectiveness.csv` — historical classification and selected strike method from the backtest
- `requirements.txt`
- `.github/workflows/daily_screen.yml`

## Market data

Price history uses Massive's adjusted daily aggregates endpoint.

Earnings logic:

1. It first tries Massive's Benzinga Earnings endpoint if your Massive account has that expansion.
2. If that endpoint is unavailable, it falls back to `yfinance` **only for qualified stock candidates**.
3. ETFs show `N/A — ETF`.
4. Missing earnings data is reported as `Unknown`; it is never fabricated.

## 1. Create the GitHub repository

Create a new **public** GitHub repository, for example:

`bollinger-put-daily-screen`

Then from the folder containing these files:

```bash
git init
git add .
git commit -m "Initial daily Bollinger put screener"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/bollinger-put-daily-screen.git
git push -u origin main
```

## 2. Add GitHub Secrets

In GitHub:

**Repository → Settings → Secrets and variables → Actions → New repository secret**

Add:

- `MASSIVE_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Never put API keys directly in this public repository.

## 3. Telegram setup

### Create/find your bot token

In Telegram, open **@BotFather** and create a bot with `/newbot`. Copy the bot token into the GitHub secret `TELEGRAM_BOT_TOKEN`.

### Find your chat ID

1. Send a message such as `hello` to your bot.
2. In a browser or terminal call:

```text
https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates
```

3. Find the numeric `chat.id` in the response.
4. Save that number as GitHub secret `TELEGRAM_CHAT_ID`.

## 4. Add your historical effectiveness file

This package already contains the historical `stock_effectiveness.csv` supplied with the build.

Whenever you rerun the full historical backtest and want the daily screener to use the new classifications, replace `stock_effectiveness.csv` and push the update to GitHub.

The daily job does **not** re-run the full historical backtest.

## 5. Test manually before relying on the schedule

In GitHub:

**Actions → Daily Bollinger Put Screen → Run workflow**

Watch the log. A qualified candidate looks like:

```text
>>> QUALIFIED: MSFT | Strategy2 | Effective | Bullish | Strike=...
```

A no-candidate day still completes normally and Telegram receives:

```text
No stocks or ETFs fit the criteria today.
```

## 6. Schedule

The workflow uses:

```yaml
schedule:
  - cron: '30 7 * * 2-6'
    timezone: 'Asia/Singapore'
```

That means **07:30 Singapore time every Tuesday, Wednesday, Thursday, Friday and Saturday**.

This is intentionally well after the corresponding U.S. Monday-Friday close. The exact U.S.-to-Singapore gap changes with U.S. daylight-saving time, but 07:30 Singapore remains after the close in either case.

## 7. Output

Each run creates:

```text
output/YYYY-MM-DD/
    daily_summary.txt
    qualified_candidates.csv
    rejected_candidates.csv
    errors.csv
    run_metadata.json
    charts/
        TICKER_Strategy1.png
        TICKER_Strategy2.png
```

GitHub Actions also uploads the output folder as a run artifact for 30 days.

Telegram receives:

1. Daily summary
2. One PNG chart for each qualified candidate
3. Qualified-candidate CSV when candidates exist

If there are zero candidates it receives the daily summary with the explicit no-candidate message.

## 8. Important entry-price convention

A signal is only known at the close of day `t`.

The first permissible live entry is the **next trading day's Open**.

Because the Singapore-morning GitHub job runs before the next U.S. Open, the script uses the signal Close only as a **provisional entry reference** for calculating the proposed strike. The output labels it that way.

## 9. SPY regime

- **Bullish:** SPY Close > 200DMA AND 200DMA 20-day slope > 0
- **Bearish:** SPY Close < 200DMA AND 200DMA 20-day slope < 0
- **Sideways/Transitional:** all other combinations

Only Bullish and Sideways/Transitional are allowed.

## 10. Massive API rate limits

The scanner makes approximately one historical aggregate request per ticker. Runtime depends on your Massive plan and rate limits. The script handles HTTP 429 with exponential backoff rather than failing immediately.

If your API plan is heavily rate-limited, a full 500+ ticker scan can take substantially longer. Keep the GitHub job timeout large enough for your plan.

## 11. Public-repository safety

Safe to commit:

- Python source
- workflow YAML
- `stock_effectiveness.csv`
- README

Do **not** commit:

- API keys
- Telegram bot token
- `.env`

The `.gitignore` already excludes `.env` and daily output.
