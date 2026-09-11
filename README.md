# Trading Universe

A modular swing-trading bot and research platform behind a Jarvis-style HUD:
a reactive core, the five questions that matter as readouts around it, and a
command line that takes text or voice. Panels exist only when summoned.

Say or type *briefing*, *show signals*, *chart NVDA*, *why did the bot reject
NVDA?*, *use recommendation*, *override to oversold reversal*, *stop all
trading*. Every command is resolved deterministically - UI and control
commands in the browser, market questions by the backend's own intent matcher
over live platform state - so every answer is traceable and nothing is
improvised. Underneath, a strictly layered trading engine scans the S&P 500 +
Nasdaq 100 with eight explainable strategies, scores every setup, and hands
each one to an independent risk engine that is the only path to an order.

The earlier 3D universe (sectors as spiral galaxies, stocks as stars) lives in
`archive/universe/` - see its README to revive it.

```
DATA  ->  FEATURES  ->  STRATEGIES  ->  SCORER  ->  REGIME SELECTOR
                                                        |
                                                   RISK ENGINE
                                                        |
                                                EXECUTION (advisory | paper | live)
                                                        |
                                                 SQLite  +  WebSocket  ->  3D universe
```

## Run it in five minutes (no accounts needed)

The platform ships with a deterministic synthetic market, so everything below
works offline before a single API key exists.

> **GitHub Pages only shows this README.** The universe is a Next.js app that
> talks to the Python backend over HTTP and a WebSocket, so both run on your
> own machine (Python 3.11+ and Node 18+). Once they are up, open
> **http://localhost:3000**.

Quickest path, from the repo root:

```powershell
# Windows
pip install -e ".\backend[dev]"
.\scripts\dev.ps1
```

```bash
# macOS / Linux
pip install -e "./backend[dev]"
./scripts/dev.sh
```

Or by hand:

```bash
# backend
cd backend
pip install -e ".[dev]"
cp ../.env.example ../.env          # defaults: DEMO data, PAPER env, ADVISORY mode
trading-universe serve              # http://127.0.0.1:8000  (docs at /docs)

# frontend, in a second terminal
cd frontend
npm install                         # .npmrc handles a react-three peer quirk
npm run dev                         # http://localhost:3000
```

Type in the command line (`/` focuses it) or hold the mic button / `Ctrl+Space`
to talk; replies are spoken unless muted. Voice input needs Chrome or Edge;
everything else works everywhere. `Esc` dismisses a panel or stops speech.

Useful CLI commands:

```bash
trading-universe scan          # one scan, printed
trading-universe briefing      # today's briefing as JSON
trading-universe import-disclosures path/to/house_ptr_export.csv --chamber house
```

## Shareable demo (one container)

`Dockerfile` builds the frontend as a static export and has the API serve it,
so one container is the whole deployment: the universe at `/`, the API at
`/api`, the WebSocket at `/ws`, docs at `/docs`. It runs on DEMO data with
`TU_READ_ONLY=true`, so visitors can fly, search, ask questions and read every
panel but cannot change modes, risk limits, or the kill switch.

Pick a host:

- **Render (free, no card):** New → Blueprint → select this repo. `render.yaml`
  does the rest and you get an `https://…onrender.com` URL. Free instances
  sleep after 15 idle minutes, so `.github/workflows/keepalive.yml` pings the
  demo every 10 minutes to keep it warm (set a repository variable `DEMO_URL`
  if your URL differs). When a cold start does happen, the HUD loads at once
  and shows "Waking up" with the bootstrap stage until the first scan lands.
- **Fly.io:** `fly launch --copy-config --yes && fly deploy` (uses `fly.toml`).
- **Anywhere that runs a container:** every push to `main` publishes
  `ghcr.io/klystrn/trading-universe:latest` via GitHub Actions, so
  `docker run -p 8000:8000 -e TU_READ_ONLY=true ghcr.io/klystrn/trading-universe`
  is a complete demo. Locally, `docker build -t trading-universe . && docker run -p 8000:8000 trading-universe`
  then open http://localhost:8000.

Drop `TU_READ_ONLY` for a private instance where you want the controls live.
Real orders remain impossible in any of these: they need `TRADING_ENV=REAL`,
`ALLOW_REAL_ORDERS=true`, Moomoo credentials, and OpenD reachable from the
container, none of which a demo deployment has.

## Operating modes and the safety model

| Mode | What happens |
|---|---|
| `ADVISORY` | scans, scores, validates and records — never sends an order |
| `PAPER_AUTO` | places qualifying orders in a paper account |
| `LIVE_AUTO` | real orders, only when **every** gate below passes |

Real money requires four independent conditions, checked at construction *and*
again at the moment of each order:

1. `TRADING_ENV=REAL` in the environment
2. `ALLOW_REAL_ORDERS=true` in the environment
3. operating mode set to `LIVE_AUTO`
4. execution explicitly armed in the System tab this session

plus Moomoo's own trading unlock. The defaults are the safe values, and the
kill switch (System tab → **STOP ALL TRADING**) persists across restarts.

## Configuration is behaviour

Trading behaviour lives in `config/*.yaml`, not in code, so the UI sliders map
onto one place and take effect on the next scan without a restart:

| File | Governs |
|---|---|
| `risk.yaml` | capital per trade, trades/day, open positions, min reward:risk, liquidity, loss-streak guard, kill switch |
| `strategies.yaml` | scoring weights, per-strategy thresholds and parameters, regime → strategy preferences |
| `freshness.yaml` | max data age per source, and which sources each strategy *requires* |
| `universe.yaml` | scan tiers, sector taxonomy, 3D layout and encoding |

Initial defaults: $150 max per trade, 3 new trades/day, 5 open positions,
1.75:1 minimum reward:risk, fractional shares on, long-only.

## Strategies

| ID | Strategy | Kind |
|---|---|---|
| S1 `quality_momentum_pullback` | Quality Momentum Pullback | standard |
| S2 `fundamental_catalyst_breakout` | Fundamental Catalyst Breakout | standard |
| S3 `quality_oversold_reversal` | Quality Oversold Reversal | standard |
| S4 `quality_volatility_squeeze` | Quality Volatility Squeeze | standard |
| S5 `value_rerating_50dma_reclaim` | Value Re-rating / 50DMA Reclaim | standard |
| P1 `congress_fresh_purchase` | Fresh Congressional Purchase | political |
| P2 `congress_consensus` | Congressional Consensus | political |
| P3 `congress_repeat_buyer` | Repeat High-Conviction Buyer | political |

Standard scoring: technical 40 + sentiment 30 + fundamental 30, execute at
≥ 70. Political: political 25 + technical 30 + sentiment 20 + fundamental 25,
execute at ≥ 75. A strategy reports sub-factor fits on 0–1; the scorer applies
the weights. Every strategy is evaluated on every cycle; only the *active* one
may execute automatically. `NO TRADE` is a valid choice.

Political strategies are signal generators, never copy-trading: a disclosure
opens the door, and fundamentals, sentiment and current technical confirmation
still have to agree. Every window is measured from the **disclosure** date.

## Data sources

| Need | Source | Status in DEMO mode |
|---|---|---|
| Quotes, candles, orders | Moomoo OpenAPI via OpenD (`pip install -e ".[moomoo]"`) | synthetic |
| Fundamentals | SEC EDGAR XBRL company facts + 8-K item codes | synthetic |
| News discovery | GDELT | synthetic |
| News enrichment | Marketaux free tier (quota tracked) | off without key |
| Sentiment | financial lexicon (default) or FinBERT (`pip install -e ".[nlp]"`) | lexicon |
| Congressional trades | House / Senate PTR exports via `import-disclosures` | synthetic |

Freshness is enforced, not assumed: the bot will never knowingly trade on data
older than the configured threshold for that strategy, and a degraded news feed
disables Catalyst Breakout while leaving Momentum Pullback tradable. The System
tab shows exactly which strategies may trade and why not.

## Repository layout

```
config/            YAML: risk, strategies, freshness, universe
data/              constituents.csv (477 names, sector/subsector)
backend/
  src/trading_universe/
    domain/        Signal, TradeThesis, Position, PoliticalTransaction, ...
    data/          providers: demo, moomoo, sec, gdelt, marketaux, disclosures, freshness
    features/      technical, fundamentals, sentiment, political, sector, regime
    strategies/    S1-S5, P1-P3
    scoring/       scorer, regime selector
    execution/     sizing, risk engine, paper broker, moomoo broker, live gates
    services/      market data tiers, scanner, ingest, health, briefing, viz payload
    analytics/     performance, strategy stats, rejected signals, politician stats
    api/           FastAPI routes + WebSocket
  tests/           167 tests
frontend/
  components/hud/  reactive core, status readouts, command line, panel host
  components/      eight summonable panels, glass primitives
  lib/intents.ts   deterministic command router; lib/voice.ts speech in/out
  charts/          Lightweight Charts candlesticks with overlays
archive/universe/  the retired 3D scene, kept for reference
```

## Tests

```bash
cd backend && pytest        # 167 tests against the deterministic demo market
cd frontend && npm run typecheck && npm run build
```

## Roadmap (from the spec)

Partial exits and trailing stops, sector-level execution permissions, forward
return backfill for rejected-signal analysis, politician follow-through
scoring, statistical strategy selection once paper history exists, and live
trading only after extended paper validation.
