---
name: market-forex-comm
version: 0.3.0
description: |
  Forex (EURUSD/USDJPY/GBPUSD/...) and commodity (gold, silver, oil WTI/Brent,
  natgas, copper) trade recommendations: classic TA + SMC (BOS/CHoCH/OB/FVG/
  liquidity sweep) + DXY overlay (inverse for XXXUSD & commodities, same-sign
  for USDXXX) + ForexFactory economic-calendar gating, news + Telegram channel
  sentiment, BUY/SELL/WAIT verdict with entry zone, stop loss, 3-tier take
  profit, risk-reward, and a narrative summary in Bahasa Indonesia.
  Walk-forward backtest harness available.
triggers:
  - forex
  - fx
  - eurusd
  - gbpusd
  - usdjpy
  - audusd
  - usdchf
  - usdcad
  - nzdusd
  - gold
  - emas
  - xau
  - silver
  - perak
  - xag
  - oil
  - minyak
  - wti
  - brent
  - gas
  - natgas
  - copper
  - tembaga
  - komoditas
language: python
entrypoint: python3 -m skills.forex_comm.analyze
---

# Forex + Commodities skill

## Routing — use `recommend` by default

For ANY user question about trading forex/komoditas: "EURUSD setup gimana",
"analisa gold", "rekomendasi XAUUSD", "USDJPY mau short", "oil arah kemana",
"emas masuk gak" — call `recommend`. It is the engine that combines TA + SMC
+ DXY overlay + economic calendar gating + news + Telegram sentiment.

Only call `analyze` if the user explicitly asks for a plain snapshot, or
`calendar` if they want today's economic events list.

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
python3 -m skills.forex_comm.analyze recommend <SYMBOL> --tf 1d --tg
python3 -m skills.forex_comm.analyze analyze <SYMBOL> --tf 1d --tg   # legacy, also emits card via --tg
```

Skip `--tg` only when the user explicitly asks for a chart attachment or a
full data drill-down (e.g. "kasih chart" / "jelasin SMC-nya panjang").

## Commands (recommend = default for trading queries)

| Command | Example | What it returns |
| --- | --- | --- |
| **`recommend <sym>`** | `recommend GOLD --tf 1d` | **verdict** (BUY/SELL/WAIT) + confidence + score + **entry_zone** + **stop_loss** + **take_profit[3]** + **risk_reward[3]** + reasoning + warnings (calendar + DXY) + SMC detectors + news_summary (RSS + Telegram) + narrative |
| `backtest <sym>` | `backtest GBPUSD --tf 1d --risk balanced` | walk-forward metrics |
| `analyze <sym>` | `analyze USDJPY --tf 1d` | legacy: snapshot + chart + calendar + narrative (NO verdict). Prefer `recommend`. |
| `price <sym>` | `price EURUSD` / `price GOLD` | spot quote (TwelveData → yfinance fallback) |
| `ta <sym> [--tf 1d]` | `ta XAUUSD --tf 4h` | raw RSI/MACD/BB/EMA/ATR/pivot |
| `calendar [--impact]` | `calendar --impact high` | today's ForexFactory events |
| `compare <a> <b>` | `compare GOLD SILVER` | side-by-side TA |
| `watchlist add/rm/list` | `watchlist add EURUSD` | manage watchlist (default: 7 majors + 6 commodities) |

### `recommend` flags
- `--tf {1h|4h|1d|1w}` (default `1d`)
- `--risk {conservative|balanced|aggressive}` (default `conservative`)
- `--no-smc` opt-out of SMC overlay (default ON)
- `--no-news` / `--no-telegram` / `--no-narrative` — opt-out toggles

## Symbols

**Forex** — 6-letter pair without slash (`EURUSD`, `USDJPY`, `GBPUSD`). Slash optional (`EUR/USD`).

**Commodities** (aliases auto-resolved to futures ticker):

| Alias | yfinance ticker | What |
| --- | --- | --- |
| `GOLD`, `XAU`, `XAUUSD` | `GC=F` | Gold futures |
| `SILVER`, `XAG`, `XAGUSD` | `SI=F` | Silver futures |
| `OIL`, `WTI` | `CL=F` | Crude oil WTI |
| `BRENT` | `BZ=F` | Crude oil Brent |
| `GAS`, `NATGAS` | `NG=F` | Natural gas |
| `COPPER` | `HG=F` | Copper |
| `PLATINUM` | `PL=F` | Platinum |
| `PALLADIUM` | `PA=F` | Palladium |

Default watchlist: 7 major forex pairs + 6 commodities (gold, silver, oil, brent, natgas, copper).

## Data sources

- **tvremix MCP (TradingView)** — primary for forex OHLCV + spot + technicals + SMC. Set `TVREMIX_API_KEY`.
- **yfinance** — fallback for commodities + forex not covered by TV.
- **ForexFactory** — economic calendar scrape (high/medium/low impact events). Anonymous.

## Hermes autonomy

Read-only. No order placement. Safe to run without confirmation.

## Caveats

- TwelveData free tier rate-limits aggressively (8 calls/min). The skill caches responses for 60s.
- For forex, when TwelveData key is missing, yfinance fallback uses `<PAIR>=X` which has 15-min delay.
- 4h timeframe is resampled from 1h on the yfinance path.
- ForexFactory occasionally changes its HTML; selectors may need updates if calendar scrape fails.
