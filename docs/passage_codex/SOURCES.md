# Sources et portée

Consultation : 21 septembre 2026. Références de méthode/infrastructure, pas preuves d'un avantage de notre stratégie crypto.

**[S1] scikit-learn — Tuning the decision threshold for class prediction.** Distingue estimation probabiliste et décision ; explique le seuil par défaut de 0,5 et l'intérêt d'un critère adapté. Dans notre application, conserver des partitions chronologiques plutôt que reprendre automatiquement une validation aléatoire.
`https://scikit-learn.org/stable/modules/classification_threshold.html`

**[S2] scikit-learn — Probability calibration.** Décrit les probabilités calibrées et les courbes de fiabilité. La calibration ne suffit pas à établir la rentabilité.
`https://scikit-learn.org/stable/modules/calibration.html`

**[S3] Freqtrade/FreqAI — Feature engineering, Outlier detection, Dissimilarity Index.** Exemple documenté de détection de contextes éloignés des observations d'apprentissage. Ne prouve pas qu'il faut rejeter les mouvements extrêmes de notre stratégie.
`https://www.freqtrade.io/en/stable/freqai-feature-engineering/`

**[S4] David H. Bailey et Marcos López de Prado — The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality (2014).** Texte de recherche des auteurs. Sert à traiter la sélection parmi de nombreux essais ; ne remplace pas une évaluation chronologique indépendante ni un modèle d'exécution réaliste.
`https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf`

**[S5] OpenAI — Custom instructions with AGENTS.md et Best practices.** Documentation sur les consignes de projet, le contexte, le périmètre et les critères de fin d'une tâche Codex. Les adresses développeur redirigent actuellement vers la documentation ChatGPT Learn.
`https://developers.openai.com/codex/guides/agents-md`
`https://developers.openai.com/codex/learn/best-practices`

**[S6] Binance — Public Data.** Documentation officielle des archives publiques, formats de bougies/transactions et checksums. Leur existence ne signifie pas que les fichiers requis ont été téléchargés dans notre environnement.
`https://github.com/binance/binance-public-data`

**[S7] QuantConnect — Slippage, key concepts.** Distingue prix attendu et prix effectivement obtenu. Même les transactions historiques ne reconstituent pas avec certitude l'exécution d'un ordre qui n'a pas existé.
`https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/slippage/key-concepts`

## Source locale principale

Archive `range_agents_v2.zip` fournie dans la conversation, lecture statique de `config.py`, `ranges.py`, `engine.py`, `learning.py`, `research.py`, `data.py`, `types.py`, `diagnostics.py` et documents de statut. Les constats sont détaillés dans `REVUE_V2.md`. Aucun dépôt connecté n'a été interrogé ; cette revue ne porte pas sur d'éventuelles modifications ultérieures dans GitHub ou Codex.
