# Prompt de reprise

Reprends Range Agents V3 dans ce dossier. Lis `AGENTS.md`, `docs/VALIDATION_V3.md`, `docs/LOGIC_REVIEW_V3.md` et `docs/IMPLEMENTATION_MATRIX_V3.md` avant d'agir.

Le périmètre est collecte authentique et observation seule. Ne lance aucun backtest, entraînement, optimisation, paper trading, démo ou ordre réel ; ne déverrouille pas la politique. Commence par `python scripts/validate_static.py`, puis le diagnostic et l'affichage du plan de collecte. Ces commandes ne nécessitent aucune donnée de marché artificielle.

Fais fonctionner la collecte du premier lot public réel, conserve ZIP/checksums/provenance et vérifie la compatibilité entre collecteur et `RealDataset`. Si des fichiers authentiques existent déjà, réutilise-les seulement après contrôle. En cas d'erreur réseau, n'invente pas de prix et garde le diagnostic exact.

Ensuite produis le catalogue de ranges et franchissements observés, sans portefeuille ni PnL hypothétique. Vérifie visuellement les niveaux majeurs avant de proposer des filtres supplémentaires. Rapporte la couverture réellement reçue, les canaux absents et les tests effectivement réalisés. Les 123 contrôles livrés ne remplacent pas la validation événementielle différée. Demande un accord distinct avant toute expérience de rentabilité.
