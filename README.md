# gizzyfx-skills

GizzyFx Terminal's trading skill library. Ports Moon Dev's SMC detectors, hermes-market-skills forex TA, and GizzyFx backtest engine into one repo.

## Skills

| Path | Source | Description |
|------|--------|-------------|
| `skills/moon-dev/` | `activer007/ordinary-claude-skills/moon-dev-trading-agents` | Moon Dev's AI trading agents reference (48+ agent patterns, RBI backtesting, ModelFactory LLM abstraction) |
| `skills/forex_comm/` | `jagres0039/hermes-market-skills` | Forex + commodities TA: OHLCV (TwelveData/Yahoo), RSI/MACD/BB/EMA/Fib, DXY overlay, economic calendar, `recommend` verdict, `backtest` subcommand |
| `skills/crypto/` | `jagres0039/hermes-market-skills` | Crypto: CoinGecko + CCXT, funding rate, F&G index, BTC dominance, SMC overlay |
| `skills/_shared/` | `jagres0039/hermes-market-skills` | Shared TA, chart, HTTP cache, signals, SMC detectors (Python) |
| `gizzyfx/smc-engine.ts` | `prop-farm-navigator/src/lib/smc-engine.ts` | TypeScript SMC engine: swings, BOS/CHoCH, order blocks, FVG, sweeps, zone |
| `gizzyfx/backtest-engine.ts` | `prop-farm-navigator/src/lib/backtest-engine.ts` | Backtest engine with 5 entry types: sma_cross, ema_cross, rsi, breakout, smc |
| `gizzyfx/smc.tsx` | `prop-farm-navigator/src/routes/smc.tsx` | SMC Analysis page (UI) |
| `gizzyfx/api/smc.ts` | `prop-farm-navigator/src/routes/api/smc.ts` | SMC Analysis API endpoint |

## Install

```bash
# Link into Hermes skills
ln -s $(pwd)/skills ~/.hermes/skills/research/market

# Install Python deps
pip install -r skills/requirements.txt
```

## Deploy

Skills auto-update on `git pull` via symlink. The GizzyFx site (`gizzyfxstrategy.dpdns.org`) deploys via Cloudflare Workers from `prop-farm-navigator`.
