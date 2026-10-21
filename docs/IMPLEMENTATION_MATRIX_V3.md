# Matrice d'implémentation — V3

« Implémenté » décrit du code. « Contrôlé » précise une preuve limitée. Aucune alternative n'a été entraînée ni backtestée et aucun optimum n'est déclaré.

| Décision du plan | Fichiers principaux | État et contrôles effectués | Validation restante |
|---|---|---|---|
| P0-00 Observation seule / données authentiques | `policy.py`, `__main__.py`, `observation.py`, `collecte/collect_real_data.py` | Chemin autonome sans moteur ; contrôle source/contrat/période/empreintes/projection ; couverture et trous ; refus sans données testé | Téléchargement + conversion + catalogue d'un vrai lot, réseau bloqué ici |
| P0-01 Objectif économique | `learning.py`, `geometry.py` | Cible R net ; régularisation et décomposition ; seuil économique ; anciennes versions refusées ; identité de calcul contrôlée avec valeurs scalaires | Entraînement chronologique autorisé et comparaison sur occasions communes |
| P0-02 Sorties comparables | `config.py`, `geometry.py`, `engine.py`, `research.py` | 2/1/0 prises partielles ; trailing indépendant ; R de référence immuable ; profils personnalisés non réécrits ; schémas/formules contrôlés | Cycle complet des remplissages/TP/BE/trailing sur événements, non exécuté |
| P0-03 Parcours de réintégration | `signals.py`, `observed_paths.py` | Temps, extrême, retour et nombre de réintégrations figés ; même bougie et variante écoulée distinctes ; état indépendant de l'acceptation d'ordre | Invariance sur vrais préfixes et comparaison de contextes |
| P1-04 Banque / approche / imbrication | `ranges.py`, `observation.py` | Banque plafonnée ; référence et alternatives enregistrées ; pivots disponibles seulement après confirmation ; niveau absent = inconnu | Vérification visuelle des structures attendues et sensibilité calcul/temps |
| P1-05 Stop structurel | `geometry.py`, `signals.py`, `engine.py` | Borne traversée ou extrême observé ; marge ; distance % recalculée sans déplacer l'ancre ; limite dépassée = refus | Risque au vrai remplissage, minimums d'exchange, partials et stops natifs |
| P1-06 Compte et allocation | `allocation.py`, `engine.py`, `metrics.py` | Priorité seulement entre signaux connus ; corrélation fermée sans ffill ; budgets fixes ; rendement calendaire et concentration ; comptes incomplets non admissibles | Tests de portefeuille sur couverture continue puis protocole d'exécution spécifique |
| P1-07 Incertitude / calibration | `learning.py`, `config.py` | Normalisation train seule ; calibration distincte ; contexte inconnu/expiré = abstention ou référence approuvée ; pas de suppression de prix extrêmes | Calibration et domaine utile avec effectifs réels suffisants ; aucun modèle entraîné |
| P1-08 Registre / essais multiples | `governance.py`, `research.py` | Journal global, hypothèses immuables, échecs conservés, dates finales réservées, reprises/empreintes testées ; un facteur par variante | Protocole statistique final sur séries calendaires ; pas de DSR naïf calculé ni de bootstrap lancé |

## Corrections transversales

Les overrides 4H/Daily sont résolus AVANT la recherche : le réglage affiché doit être celui réellement utilisé. Une grille spécifiée n'est plus remplacée silencieusement pour la réintégration. Deux sélections de stratégies qui demandent des seuils partagés incompatibles ne sont pas assemblées en écrasant l'une par l'autre : le conflit bloque la candidature.

Les modèles injectés par dépendance doivent passer les mêmes vérifications d'approbation/empreinte que ceux chargés sur disque. Un retournement différé conserve le prix du signal initial et enregistre séparément l'observation d'exécution. Les indicateurs EX_POST ne sont pas admissibles dans le vecteur d'entrée.

## Ce qui n'est pas livré comme fonction validée

Un top 50 historique reconstitué, des règles historiques signées de chaque contrat, un transport d'ordres live, le carnet historique complet et des modèles entraînés ne sont pas présents. L'évaluation sur instruments laissés de côté et le Deflated Sharpe Ratio sont décrits dans le protocole, pas exécutés ni présentés comme des labels de qualité. La nouvelle banque ne démontre pas encore qu'elle correspond visuellement aux ranges préférés du propriétaire.

## Préparation du dépôt — 22 octobre 2026

La préparation GitHub conserve le code applicatif et la politique d’observation seule. Les 123 contrôles statiques existants ont été réexécutés avec succès. Le README anglais, le guide français préservé, les exclusions Git et le manifeste ont été préparés pour publication. Les détails et les limites sont consignés dans [PUBLICATION_NOTES.md](PUBLICATION_NOTES.md).
