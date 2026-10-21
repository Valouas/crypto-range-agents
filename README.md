# Crypto Range Agents

**A Python research toolkit for observing horizontal crypto ranges, intrabar breakouts, and same-candle reintegrations from verified public market archives.**

The default workflow collects source archives, verifies their checksums and derivation, and builds an event catalogue. Four-hour and daily structures are processed independently, with signal features frozen at the time they become observable. Post-event observations are exported separately.

This repository contains the Range Agents 3.0.0 prototype. Observation is enabled; backtesting, model training, paper trading, and synthetic-market generation remain disabled by the included runtime policy. There is no live-order connector.

[Guide en français](README.fr.md) · [Implementation status](docs/IMPLEMENTATION_MATRIX_V3.md) · [Current verification](docs/PUBLICATION_NOTES.md)

## What it contains

| Component | Purpose |
| --- | --- |
| Public-data collector | Downloads Binance USD-M archive files and keeps source checksums and receipts. No trading API key is required. |
| Range and signal logic | Identifies horizontal structures from closed 4H/daily bars, then observes crossings and reintegrations in received transaction events. |
| Provenance checks | Verifies source identity, archive hashes, converted events, requested periods, and missing coverage. |
| Observation reports | Produces coverage tables, timestamped signal catalogues, and a separate `EX_POST` path catalogue. |
| Research registry | Records hypotheses and viewed periods, preserves unsuccessful attempts, and guards reserved holdout periods. |
| Gated research modules | Includes execution hypotheses, allocation, exit profiles, and model-filter code for later separately authorized validation. |

The word “agents” refers to the breakout and reintegration strategy components. The repository does not require an LLM service.

## Quick start: local checks

Requirements: **Python 3.11 or later**. Run commands from the repository root.

```bash
python -m venv .venv
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

python scripts/validate_static.py
python -m range_agents doctor
python -m range_agents check-config --config configs/observation.json
python -m range_agents collect --task plan
```

Installing dependencies requires package-download access. The four project commands above inspect local code, configuration, and the collection plan; they do not download market data or run a trading experiment.

No credentials are required. `.env.example` intentionally contains no settings because the observation workflow uses public archives and JSON configuration files.

## Collect and observe real data

Review `collecte/collection_plan.json` before starting a download. The supplied example requests BTCUSDT, ETHUSDT, and SOLUSDT: 4H/daily structure archives from January 2021 through August 2026, and aggregate transactions for January 1–2, 2025. This is a requested collection scope; no market archive is bundled with this repository.

The following collection commands use the network. Run them sequentially:

```bash
python -m range_agents collect --task structures --data data/reel
python -m range_agents collect --task transactions --data data/reel
python -m range_agents collect --task verify --data data/reel
python -m range_agents observe \
  --config configs/observation.json \
  --data data/reel \
  --out runs/observation
```

Missing or invalid data produces a diagnostic. The observer does not fill missing intervals with generated prices. Observation output is created only from the data actually available and verified.

## Project layout

| Path | Contents |
| --- | --- |
| `collecte/` | Public archive collector and collection plan |
| `range_agents/` | Range logic, signals, provenance, reports, and research modules |
| `configs/` | Observation-only example configurations |
| `tests_static/` | Schema, scalar calculation, policy, and metadata checks |
| `tests_dynamic/` | Deferred acceptance tests requiring real data and explicit scope |
| `docs/` | Design notes, implementation matrix, and validation limitations |
| `runtime_policy.json` | Capability gates used by the command-line workflow |

The numbered Windows batch files provide the same installation, checking, planning, collection, and observation steps. They have not been verified on Windows in this preparation.

## Validation and limits

The default test target is `tests_static`. These checks cover configuration, geometry, provenance metadata, policy gates, and research-registry behaviour. They do not establish a profitable strategy or validate the complete event-driven order lifecycle.

- The included universe contains three contracts, not a reconstructed historical top 50.
- The transaction example covers two days; it is not complete intrabar coverage for the full structure period.
- A same-candle reintegration is recorded distinctly from a confirmed swing-failure pattern.
- Strategy, cost, and exchange-rule values are research assumptions. They are not optimized parameters or verified historical contract rules.
- No trained model, live execution integration, or market-performance result is supplied.
- Genuine-data conversion, observation, and event-driven research still need the acceptance work listed in [Dynamic validation required](docs/DYNAMIC_VALIDATION_REQUIRED.md).

Keep `runtime_policy.json` and the observation configuration in their delivered state for this workflow. Optional research dependencies are listed separately in `requirements-optional.txt`.

## En français

Outil de recherche Python pour collecter et vérifier des archives publiques, identifier des ranges horizontaux en 4H/Daily, puis observer les franchissements et réintégrations intrabougie. Le mode livré est l’observation seule. Le [guide français](README.fr.md) et les documents techniques détaillent les hypothèses et les validations restantes.
