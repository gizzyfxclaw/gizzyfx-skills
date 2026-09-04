---
name: market-saham-idn
version: 0.3.0
description: |
  Indonesian-listed stock (IDX / BEI) trade recommendations: classic TA + IHSG
  context + fundamental overlay (PER vs sector, EPS forward, dividend yield),
  RSS news sentiment (Bisnis Indonesia, Kontan, IDN Financials) + Telegram
  channel sentiment, IHSG composite snapshot, BUY/HOLD verdict with entry zone,
  stop loss, 3-tier take profit, risk-reward, and a narrative summary in Bahasa
  Indonesia. Cash market — no shorting.
triggers:
  - saham
  - ihsg
  - idx
  - bei
  - bursa
  - lq45
  - bbri
  - bbca
  - bmri
  - bbni
  - tlkm
  - asii
  - unvr
  - indf
  - icbp
  - tpia
  - ".jk"
language: python
entrypoint: python3 -m skills.saham_idn.analyze
---

# Saham IDN skill

## Routing — use `recommend` by default

For ANY user question about trading saham, "saham X gimana", "BBRI mau beli",
"analisa BBCA", "rekomendasi saham bank", "harga TLKM bagus gak buat masuk" —
call `recommend`. It is the engine that combines TA + fundamental + IHSG
context + news + Telegram sentiment, and outputs BUY/HOLD verdict.

Only call `analyze` if the user explicitly asks for a plain snapshot or
"ringkasan teknikal aja".

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
python3 -m skills.saham_idn.analyze recommend <SYMBOL> --tf 1d --tg
python3 -m skills.saham_idn.analyze analyze <SYMBOL> --tf 1d --tg   # legacy, also emits card via --tg
```

Skip `--tg` only when the user explicitly asks for a chart attachment or a
full data drill-down (e.g. "kasih chart" / "jelasin SMC-nya panjang").

## Commands (recommend = default for trading queries)

| Command | Example | What it returns |
| --- | --- | --- |
| **`recommend <ticker>`** | `recommend BBRI --tf 1d` | **verdict** (BUY/HOLD) + confidence + score + **entry_zone** + **stop_loss** + **take_profit[3]** + **risk_reward[3]** + reasoning (TA + fundamental: PER, dividend yield, EPS, IHSG context) + warnings + news_summary (RSS + Telegram) + narrative |
| `analyze <ticker>` | `analyze TLKM --tf 1d` | legacy: snapshot + chart + news + IHSG + narrative (NO verdict). Prefer `recommend`. |
| `price <ticker>` | `price BBRI` | last, prev close, range, mcap, PER, EPS, dividend |
| `ihsg` | `ihsg` | snapshot of the IHSG composite (`^JKSE`) |
| `ta <ticker> [--tf 1d]` | `ta BBCA --tf 4h` | raw RSI/MACD/BB/EMA/ATR/pivot |
| `news [keyword]` | `news bank` | RSS news matching keyword |
| `compare <a> <b>` | `compare BBRI BBCA` | side-by-side fundamentals + TA |
| `watchlist add/rm/list` | `watchlist add ASII` | manage watchlist (default: LQ45 core) |

### `recommend` flags
- `--tf {1d|1w}` (intraday timeframes unreliable due to yfinance 15-min delay)
- `--risk {conservative|balanced|aggressive}` (default `conservative`)
- `--no-news` / `--no-telegram` / `--no-narrative` — opt-out toggles

## Tickers

Use the 4-letter IDX code (`BBRI`, `BBCA`, `TLKM`). The skill auto-appends `.JK` for yfinance. Composite index: `^JKSE`.

Default curated watchlist: `BBRI BBCA BMRI BBNI TLKM TPIA ASII UNVR INDF ICBP`.

## Data sources

- **yfinance** — `<ticker>.JK` OHLCV + Ticker.info fundamentals. Anonymous, free, no auth. (IDX stocks are not covered by TradingView, so yfinance remains primary.)
- **RSS** — Bisnis.com, Kontan, IDN Financials. No auth.

## Hermes autonomy

Read-only. No order placement, no broker integration. Safe to run without confirmation.

## Caveats

- yfinance fundamentals for IDX tickers can be sparse; missing fields are returned as `null`.
- IDX intraday data has a 15-min delay on the free Yahoo feed.
- Some 6-letter IDX codes (mis. `ARTO.JK`) also work.
- 4h timeframe is resampled from 1h (yfinance doesn't expose 4h natively).
