# SHADOW Trading & Strategy Validation Engine

A read-only / simulated strategy-validation project derived from a larger multi-exchange trading research system. It evaluates directional market signals, records hypothetical positions, applies risk rules, and captures evidence without submitting live orders.

## What this project demonstrates

- Python-based market-data ingestion from public Coinbase and Kraken endpoints
- Directional LONG/SHORT signal analysis using EMA structure, momentum, RSI, and volume conditions
- Simulated position lifecycle with stop-loss, take-profit, and signal-flip exits
- Risk-based hypothetical position sizing
- Kraken strategy monitoring using public OHLC data
- Persistent SHADOW state and JSONL event logging
- Hypothetical checkpoint tracking at 15m, 30m, 1h, 4h, 12h, and 24h
- Atomic state writes and basic process-safety controls
- Explicit separation between strategy research and live order authority

## Safety architecture

This public edition intentionally contains **no live-order execution function** and does not require exchange credentials. `live_authority` remains false in the example configuration. The project is intended for software engineering, market-data analysis, and strategy-validation demonstration—not as financial advice or a promise of trading performance.

## Components

`src/futures_shadow_engine.py` analyzes public Coinbase market candles, creates simulated LONG/SHORT positions, applies configurable risk/exit rules, and records SHADOW results.

`src/kraken_shadow_engine.py` analyzes Kraken public OHLC data for a small multi-asset universe while keeping execution isolated and disabled.

`src/hypothetical_tracker.py` records hypothetical opportunities and evaluates later checkpoints, including gross movement, estimated net movement, maximum favorable excursion (MFE), and maximum adverse excursion (MAE).

`config/shadow_config.example.json` contains non-secret demonstration settings with live authority disabled.

## Running the engines

Use Python 3.11 or newer.

```powershell
python .\src\futures_shadow_engine.py
```

or

```powershell
python .\src\kraken_shadow_engine.py
```

Each engine runs continuously on an approximately 60-second cycle and writes local state/log artifacts that are excluded by `.gitignore`.

## Public-repository boundaries

The public edition excludes the private live Coinbase spot bots, exchange credentials, email credentials, account balances, production control files, private telemetry, compiled caches, personal filesystem paths, and live order-authority code.

## Portfolio context

This project demonstrates automation, API/data integration, defensive control design, state management, monitoring, and evidence-driven testing. It is presented as an engineering and strategy-validation project rather than a claim of investment performance.
