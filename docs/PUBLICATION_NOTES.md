# Repository preparation and validation

Prepared on **22 October 2026** from `range_agents_v3.zip`. The application remains version **3.0.0**.

## Changes for publication

- Added an English project overview and reproducible command-line quickstart.
- Preserved the original French guide as `README.fr.md`, with a link to this current validation note.
- Expanded `.gitignore` for credentials, generated data, logs, databases, development environments, and build output.
- Added a comment-only `.env.example`: this project does not require credentials for public-data observation.
- Removed the original generated files under `docs/evidence/` and the nested legacy V2 test ZIP. The historical V3 validation narrative remains available and is labelled as historical.
- Refreshed the file-integrity manifest and added preparation provenance to `RELEASE.json`.

Application source, JSON strategy examples, collection dates, runtime policy, and dependency pins were preserved. No license was present in the source archive; this preparation does not introduce a license.

## Verification actually performed

```bash
python scripts/validate_static.py
```

Result: **123 existing static tests passed**, exit code 0. The launcher also compiled the application and collector and validated all four example configurations.

Runtime: Python **3.12.14**, NumPy **2.3.5**, pandas **2.2.3**, requests **2.32.5**, pytest **9.0.2**. Missing test dependencies were installed into a separate temporary environment, outside the publication directory.

A syntax pass parsed every included Python file. A targeted text scan found no private-key blocks, GitHub or Telegram token patterns, credential assignments, email addresses, wallet addresses, or Windows user-home paths. This is a scoped review, not a guarantee that arbitrary secrets are impossible.

## Scope and remaining work

The tests cover schemas, scalar calculations, capability guards, and metadata/registry behaviour. The four deferred dynamic acceptance tests were not executed. No market-data download, backtest, optimization, model training, paper trading, synthetic-market generation, or live order was performed.

The real-data observation pipeline and complete event-driven lifecycle still require the work described in [DYNAMIC_VALIDATION_REQUIRED.md](DYNAMIC_VALIDATION_REQUIRED.md). No claim of trading performance follows from the passing static checks.

## Preparation decisions

| Decision | Reason |
| --- | --- |
| Preserve observation-only defaults | Matches the supplied project policy and the scope actually checked. |
| Keep research modules gated | Their full event-driven behaviour has not been accepted in this preparation. |
| Keep the three-symbol collection plan explicit | Avoids presenting an example universe as a historical top-50 data set. |
| Exclude generated historical logs and legacy test archive | Keeps the repository focused on current source and reproducible checks. |
| Preserve code and dependency versions | Publishing the existing project does not require a strategy redesign. |
