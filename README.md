# SMC Liquidity-Sweep Telegram Alert Bot

A first working MVP for scanning six Forex pairs and sending clean **A+ (6/6)** and **A Possible (5/6)** alerts to Telegram.

The project uses:

- GitHub repository
- Render Web Service for health checks and controlled testing
- Render Background Worker for continuous scanning
- Twelve Data for candles and trial/live WebSocket prices
- Telegram Bot API for alerts and `/track` commands
- Fixed **$400 entry-to-SL price risk**
- MT5-style Forex volume calculation for a USD account

> Alerts only. The MVP does not place MT5 orders. Test all calculations on an MT5 demo account before relying on them.

## 1. Markets and timeframes

Enabled pairs:

```text
EUR/USD
GBP/USD
USD/JPY
AUD/USD
USD/CAD
GBP/JPY
```

Timeframes:

- H4: primary structure and dealing range
- H1: confirms bias and higher-timeframe zone
- M15: sweep, displacement, CHoCH/MSS, FVG/OB and signal
- M5: A+ retracement confirmation only

DAX/GER40 is disabled until its data-feed symbol and IC Markets contract specification are confirmed.

## 2. Signal grades

- **A+**: 6/6, sent as an actionable entry alert and automatically tracked
- **A Possible**: 5/6, full levels are shown, but it says `No trade yet.`
- Below 5/6: no alert

Core conditions are mandatory:

- HTF bias
- Liquidity sweep
- Displacement + CHoCH/MSS

The full measurable rulebook is in [`STRATEGY_SPEC.md`](STRATEGY_SPEC.md).

## 3. Project structure

```text
smc-alert-bot/
├── app/
│   ├── alerts/
│   │   ├── formatters.py
│   │   └── telegram.py
│   ├── data/
│   │   └── twelve_data.py
│   ├── strategy/
│   │   ├── engine.py
│   │   ├── indicators.py
│   │   ├── structure.py
│   │   └── zones.py
│   ├── api.py
│   ├── models.py
│   ├── risk.py
│   ├── settings.py
│   ├── state.py
│   └── worker.py
├── config/symbols.yaml
├── tests/
├── .env.example
├── render.yaml
├── requirements.txt
└── STRATEGY_SPEC.md
```

## 4. Create the GitHub repository

1. Download and unzip this project.
2. On GitHub, create a new repository named `smc-alert-bot`.
3. Do **not** initialize it with a README because this project already has one.
4. Open a terminal inside the project folder.
5. Run:

```bash
git init
git add .
git commit -m "Initial SMC alert bot MVP"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/smc-alert-bot.git
git push -u origin main
```

Never commit `.env`, API keys, bot tokens, or chat IDs.

## 5. Run locally

Python 3.11 or newer is recommended.

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

macOS/Linux:

```bash
source .venv/bin/activate
```

Install packages:

```bash
pip install -r requirements.txt
```

Copy the environment template:

```bash
cp .env.example .env
```

On Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Fill in `.env`:

```env
TWELVE_DATA_API_KEY=your_private_key
TELEGRAM_BOT_TOKEN=your_private_token
TELEGRAM_CHAT_ID=your_chat_id
API_AUTH_TOKEN=create_a_long_random_secret
STATE_DB_PATH=./smc_state.sqlite3
```

## 6. Run tests

```bash
pytest -q
```

## 7. Start the local Web Service

```bash
uvicorn app.api:app --reload
```

Health check:

```text
http://127.0.0.1:8000/health
```

Expected response:

```json
{"status":"ok"}
```

The protected test endpoints require:

```text
Authorization: Bearer YOUR_API_AUTH_TOKEN
```

### Test Telegram

```bash
curl -X POST http://127.0.0.1:8000/test/telegram \
  -H "Authorization: Bearer YOUR_API_AUTH_TOKEN"
```

### Test market data

Because the pair contains `/`, keep it in the URL path:

```bash
curl http://127.0.0.1:8000/test/market/EUR/USD \
  -H "Authorization: Bearer YOUR_API_AUTH_TOKEN"
```

### Test lot size

```bash
curl -X POST http://127.0.0.1:8000/test/lot-size \
  -H "Authorization: Bearer YOUR_API_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"symbol":"EUR/USD","entry":1.08740,"stop_loss":1.08580}'
```

Expected lot size for the example is approximately `2.50` lots.

### Test one live strategy scan

```bash
curl -X POST "http://127.0.0.1:8000/test/scan/EUR/USD?send=false" \
  -H "Authorization: Bearer YOUR_API_AUTH_TOKEN"
```

Change `send=false` to `send=true` only when you intentionally want a qualifying test alert sent to Telegram.

## 8. Start the local Background Worker

```bash
python -m app.worker
```

The worker will:

1. Scan completed M15 candles.
2. Build H1 and H4 candles locally.
3. Fetch M5 only when a setup needs A+ confirmation.
4. Send A or A+ Telegram alerts.
5. Stream prices over Twelve Data WebSocket when available.
6. Track A+ signals automatically.
7. Track an A signal after a Telegram command such as:

```text
/track EURUSD
```

Other commands:

```text
/status
/help
```

## 9. Twelve Data Basic 8 credit design

The MVP is deliberately limited to the six Forex pairs.

Each normal scan uses:

- 6 M15 requests
- Up to 2 extra M5 requests only when confirmation is needed

Scanning once per completed M15 candle uses about 576 daily REST credits before occasional M5 confirmations. The worker skips most weekend hours. Monitor Twelve Data usage and reduce testing requests if the daily limit approaches 800.

The Basic plan provides trial WebSocket capacity. If the subscription is unavailable, the worker sends a warning and continues scanning on completed M15 candles. Entry/SL/TP alerts can then be delayed. Full continuous streaming generally requires a WebSocket-capable paid plan.

## 10. Deploy to Render

The included `render.yaml` creates:

- `smc-alert-api`: free Web Service for testing
- `smc-alert-worker`: Starter Background Worker
- A 1 GB persistent disk attached to the worker for SQLite signal state

A Render Background Worker cannot use the free instance type, so the worker has a cost. Review the price shown by Render before confirming deployment.

### Deployment steps

1. Push the repository to GitHub.
2. Sign in to Render.
3. Choose **New → Blueprint**.
4. Connect the `smc-alert-bot` GitHub repository.
5. Render reads `render.yaml`.
6. Enter the requested secret values for both services:
   - `TWELVE_DATA_API_KEY`
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `API_AUTH_TOKEN` for the Web Service
7. Review the worker charge and disk charge.
8. Click **Deploy Blueprint**.
9. Wait until both services show a successful deploy.

## 11. Test the Render Web Service

Open:

```text
https://YOUR-WEB-SERVICE.onrender.com/health
```

Expected:

```json
{"status":"ok"}
```

Then test Telegram:

```bash
curl -X POST https://YOUR-WEB-SERVICE.onrender.com/test/telegram \
  -H "Authorization: Bearer YOUR_API_AUTH_TOKEN"
```

You should receive:

```text
✅ Telegram test successful
```

## 12. Verify the Background Worker

Open the worker's **Logs** tab in Render. Look for:

```text
Starting M15 scan for 6 symbols
WebSocket subscribed
Scan complete
```

Telegram should also receive the worker startup message.

If the WebSocket trial is unavailable, the worker will send a warning. Strategy scans still continue.

## 13. Lot-size rule

The MVP uses public standard Forex defaults for IC Markets EU/Australia:

```text
Contract size: 100,000 base-currency units
Minimum lot: 0.01
Lot step: 0.01
Account currency: USD
Price risk: $400 from entry to SL
```

Formula:

```text
Risk for 1.00 lot in quote currency
= abs(entry - SL) × 100,000

Risk for 1.00 lot in USD
= quote-currency risk × quote-to-USD conversion

Lot size
= 400 ÷ risk for 1.00 lot in USD
```

The final volume is rounded down to the nearest `0.01` lot. Commission and spread are excluded.

Before using the output on a live account, compare several examples against the **Specification** and order calculator inside your own MT5 terminal. Broker settings inside MT5 remain authoritative.

## 14. Deployment checklist

- [ ] GitHub repository created
- [ ] `.env` excluded from GitHub
- [ ] Twelve Data API key configured
- [ ] Telegram token configured
- [ ] Telegram chat ID configured
- [ ] Local tests pass
- [ ] Local `/health` works
- [ ] Local Telegram test arrives
- [ ] EUR/USD lot-size test returns about 2.50 lots
- [ ] Code pushed to GitHub
- [ ] Render Blueprint deployed
- [ ] Render Web Service health check works
- [ ] Render Telegram test arrives
- [ ] Background Worker startup message arrives
- [ ] Six symbols appear in worker logs
- [ ] WebSocket subscription succeeds, or fallback warning is understood
- [ ] MT5 demo comparison completed before live use

## 15. Later improvements

After forward testing the MVP:

- Add a proper backtesting engine
- Add DAX/GER40 with verified broker specifications
- Store signal statistics in Postgres
- Add session filters
- Add economic-news avoidance
- Add chart screenshots to Telegram
- Add correlation and daily-loss controls
- Add MT5 execution only after the alert system is proven reliable
