---
name: market-crypto
version: 0.3.0
description: |
  Crypto market intelligence: live price, full TA stack (RSI/MACD/BB/EMA + SMC
  market structure / order blocks / FVG / liquidity sweeps), trade
  recommendation (LONG/SHORT/WAIT with entry/SL/TP + RR + suggested leverage),
  news + Telegram channel sentiment (VADER + finance keywords), Fear & Greed,
  Binance funding rate, BTC dominance, and a narrative summary in Bahasa
  Indonesia. Walk-forward backtest harness available.
triggers:
  - crypto
  - bitcoin
  - btc
  - ethereum
  - eth
  - solana
  - sol
  - coin
  - token
  - altcoin
  - defi
  - "fear and greed"
  - "fng"
language: python
entrypoint: python3 -m skills.crypto.analyze
---

# Crypto skill

## Routing — use `recommend` by default

For ANY user question about trading, direction, entry, buy/sell, "analisa",
"rekomendasi", "gimana arahnya", "mau beli/jual", "setup", "sinyal", "pump",
"dump" — call `recommend`. It is the engine that combines TA + SMC + macro +
news + Telegram sentiment and outputs the actionable verdict.

Only call `analyze` if the user explicitly asks for a plain TA snapshot,
"chart aja", or "ringkasan teknikal" without asking for a decision.

## Output format — ALWAYS use `--tg`

Append `--tg` to **every** `recommend` and `analyze` call. It makes the skill
emit a pre-rendered plain-text Telegram card (verdict + plan + R/S levels +
explicit LONG/SHORT trigger conditions + 3 reasoning bullets + macro tags +
NFA). The card is the message body — relay it verbatim to the user.

DO NOT re-narrate the card into "Current Snapshot / Critical Levels / Last 7
Candles / Skenario / Rekomendasi" essays. The card is intentionally terse so
the user gets actionable info at a glance.

```bash
# Recommended invocation (used for ALL market queries):
python3 -m skills.crypto.analyze recommend <SYMBOL> --tf 1d --tg
python3 -m skills.crypto.analyze analyze <SYMBOL> --tf 1d --tg   # legacy, also emits card via --tg
```

Skip `--tg` only when the user explicitly asks for a chart attachment or a
full data drill-down (e.g. "kasih chart" / "jelasin SMC-nya panjang").

## Commands (recommend = default for trading queries)

| Command | Example | What it returns |
| --- | --- | --- |
| **`recommend <symbol>`** | `recommend BTC --tf 1d` | **verdict** (LONG/SHORT/WAIT) + confidence + score + **entry_zone** + **stop_loss** + **take_profit[3]** + **risk_reward[3]** + **suggested_leverage_x** + reasoning + warnings + SMC detectors (OB/FVG/sweeps/zone) + news_summary (RSS + Telegram) + narrative |
| `backtest <symbol>` | `backtest BTC --tf 1d --risk balanced` | walk-forward metrics (trades, win%, total R, profit factor, max DD, expectancy) |
| `analyze <symbol>` | `analyze SOL --tf 1d` | legacy: snapshot + chart PNG + news + narrative (NO verdict). Prefer `recommend`. |
| `price <symbol>` | `price BTC` | live USD/IDR, mcap, 24h vol, 24h change |
| `ta <symbol> [--tf 1d]` | `ta ETH --tf 4h` | raw RSI/MACD/BB/EMA/ATR/pivot |
| `news [symbol]` | `news BTC` | latest CryptoPanic posts |
| `compare <a> <b>` | `compare BTC ETH` | side-by-side TA snapshot |
| `watchlist add/rm/list [sym]` | `watchlist add BTC` | manage persistent watchlist |

### `recommend` flags
- `--tf {1h|4h|1d|1w}` (default `1d`)
- `--risk {conservative|balanced|aggressive}` (default `conservative`: `|score|≥4 & RR≥2`)
- `--mtf` enable multi-timeframe confluence (1w / 1d / 4h)
- `--no-smc` opt-out of Smart Money Concepts overlay (default ON)
- `--no-news` / `--no-telegram` opt-out of news/Telegram sentiment
- `--no-narrative` skip LLM narrative

Output is JSON to stdout. Charts are saved to `$HERMES_CHART_OUT` (default `/tmp/hermes-charts/`) and the absolute path is included in the JSON as `chart_path`.

## Symbols

Use the bare ticker (`BTC`, `ETH`, `SOL`, `DOGE`). The skill maps it to:
- CoinGecko ID (`bitcoin`, `ethereum`, `solana`, …) for price + market data.
- CCXT pair `<SYM>/USDT` for OHLCV via Binance public REST.

Custom mappings can be added in `feeds.py:_COINGECKO_IDS`. For coins not in the map, the lowercased ticker is tried as a CoinGecko ID directly.

## Data sources

- **tvremix MCP (TradingView)** — primary for crypto OHLCV + spot + technicals + SMC. Set `TVREMIX_API_KEY`.
- **CoinGecko** — primary for price + market cap + rank + ATH. Free Demo tier or anonymous.
- **yfinance** — fallback for coins not covered by TradingView.
- **DeFiLlama** — `/tvl/{protocol}`, chain TVL. No auth.
- **CryptoPanic** — `/posts/`. Requires `CRYPTOPANIC_API_KEY` (free 200/day).
- **alternative.me** — Fear & Greed `/fng/?limit=1`. No auth.

## Hermes autonomy

Read-only by design. No trade execution, no signing, no on-chain calls. Safe to run without confirmation. The agent should still apply rate-limit prudence (max ~10 analyze calls/min).

## Caveats

- Stablecoins (USDT, USDC) work for price queries but TA is meaningless.
- Memecoins outside the curated ID map need either the explicit CoinGecko slug or the CCXT pair name (`PEPE/USDT`).
- TwelveData and Glassnode are NOT used — keeping the crypto skill 100% free tier.
