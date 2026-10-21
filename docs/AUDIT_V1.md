# Audit technique de Range Agents V1

## Périmètre et vérifications

Archive examinée : `range_agents_v1.zip`, version livrée dans cette conversation.

SHA256 de l’archive : `5691217b702a5dcf8fc0fec5ce026d5f6ab977b6a896b85e4f41b3f501d6475c`.

Les modules de configuration, collecte, détection, replay, recherche et les tests ont été lus. La suite existante a été réexécutée : **38 tests, 38 réussites**. Aucun ordre réel, aucun entraînement de modèle et aucun backtest sur un historique de marché n’ont été effectués dans cet audit. Le téléchargement réseau n’a pas été retesté. Les constats ci-dessous ne sont pas des résultats de rentabilité. L’archive originale n’a pas été modifiée.

## 1. Blocage logique du pilote : nombre d’épisodes inatteignable

**Priorité : corriger avant d’interpréter une recherche.**

Références : `configs/pilot.json`, `range_agents/research.py` (`partitions`, `sweep`), `range_agents/engine.py` (`install`, `run`, `summary`).

Le pilote utilise la période du 1er janvier au 1er juillet 2025, fin exclusive. Le découpage effectif est :

| Partition | Début UTC | Fin exclusive UTC | Durée |
|---|---|---|---:|
| Apprentissage | 2025-01-01 | 2025-04-19 | 108 jours |
| Validation | 2025-04-19 | 2025-05-25 | 36 jours |
| Test final | 2025-05-25 | 2025-07-01 | 37 jours |

Le moteur n’accepte qu’un épisode actif par livre symbole/timeframe. Un épisode n’est retiré qu’après son expiration et en l’absence de position ouverte. La configuration fixe cette expiration à 24 bougies de 4H (quatre jours) ou 14 bougies Daily (14 jours). Épuiser ses tentatives ne libère pas immédiatement cet épisode.

En outre, `install` refuse tout range dont la période de construction commence avant la partition. Les plus petites fenêtres sont de 12 bougies 4H (deux jours) et sept bougies Daily. Enfin, `run` interdit les nouvelles entrées dans les 72 dernières heures plus une minute en 4H, et les 120 dernières heures plus une minute en Daily.

Avec des données idéales permettant un nouveau range dès que possible, les bornes supérieures sont :

| Partition | Timeframe | Maximum théorique d’épisodes pouvant avoir une entrée | Minimum exigé |
|---|---|---:|---:|
| Apprentissage | 4H | 26 | 15 |
| Apprentissage | Daily | 7 | 15 |
| Validation | 4H | 8 | 10 |
| Validation | Daily | 2 | 10 |

Ce sont des **bornes supérieures**, pas des nombres de trades observés. Des structures inexistantes ou des positions encore ouvertes ne pourraient que diminuer ces nombres.

Dérivation : pour une partition `[a,b)`, la première installation possible est `a + min_lookback × durée_bougie`. Le dernier instant d’entrée est `b - détention_max - 1 minute`. Deux installations successives sont séparées d’au moins la durée d’expiration. Le maximum est donc `max(0, floor((dernier_instant - première_installation) / expiration) + 1)`.

**Conséquence : les deux timeframes du pilote sont incapables de satisfaire tous les critères d’admissibilité, indépendamment de leur performance de prix.** Une sortie `NO_ELIGIBLE_CANDIDATE` ne permettrait donc pas de conclure que l’idée de trading échoue.

Correction proposée : contrôle préalable de faisabilité ; historique et partitions suffisamment longs ; initialisation des structures à partir du passé déjà connu ; gestion explicite du cycle de vie des épisodes. Ne pas abaisser arbitrairement les exigences statistiques pour faire apparaître un gagnant. Les trades dont les résultats chevauchent les partitions doivent rester purgés ou traités selon une convention causale explicite.

## 2. Les stratégies n’ont pas encore des gestions indépendantes

Référence : `range_agents/engine.py`, `Replay.__init__`, `enter`, `levels` ; `research.py`, `sweep`.

Breakout et réintégration utilisent le même dictionnaire `strategy`, notamment le stop, les objectifs, les fractions, le déclenchement du break-even et le trailing. La sélection d’une variante est faite pour un couple symbole/timeframe sur leurs résultats combinés. Les journaux conservent bien le nom de l’agent, mais ce n’est pas encore une recherche autonome par stratégie.

Correction proposée : paramètres séparés par stratégie ; rapports individuels ; recherche des variantes sur chaque famille de signaux ; puis évaluation du portefeuille commun, avec un risque équivalent entre politiques. L’optimisation conjointe reste une expérience possible, mais doit être identifiée comme telle.

Aucun modèle d’apprentissage automatique n’est entraîné dans la V1 : il s’agit d’une grille finie de paramètres, avec validation manuelle, ce que la documentation annonce correctement.

## 3. Les structures longues sont limitées par les fenêtres

Références : `configs/pilot.json`, `range_agents/ranges.py`, `build_schedule`.

Les fenêtres disponibles sont 12/24/48/96 bougies en 4H et 7/14/30/60 bougies en Daily. Le détecteur ne peut donc pas représenter dans sa totalité un range de plus de 16 jours en 4H ou de plus de 60 jours en Daily, même si un sous-range peut être retenu.

Cette limite doit être confrontée à la demande de structures majeures et aux exemples de ranges de plusieurs mois. Proposition : sélection causale de fenêtres plus larges ou détecteur d’épisodes à durée variable, avec sauvegarde des bornes et de leur instant de disponibilité. Conserver la définition par les extrêmes ; ne pas déplacer rétroactivement les niveaux pour améliorer les résultats.

Autre précision : le champ nommé `width_atr` utilise dans ce code une médiane des true ranges de la fenêtre, et non l’ATR classique à lissage de Wilder. Il faut le documenter ou le renommer pour éviter des comparaisons trompeuses avec un indicateur graphique.

## 4. Replay intraminute : hypothèses, pas données observées

Référence : `range_agents/engine.py`, `segment`, `run`.

Chaque minute est rejouée selon deux parcours monotones : ouverture-haut-bas-clôture et ouverture-bas-haut-clôture. Des horodatages artificiels sont affectés aux trois segments. Plusieurs événements d’un même segment peuvent porter le même horodatage.

Les ordres, dès qu’un seuil est traversé, sont exécutés selon les hypothèses de glissement fixe. Le code ne simule pas un carnet réel, une file d’attente, la latence de soumission ou d’annulation, des exécutions incomplètes, ni les quantités minimales et pas d’ordre de l’exchange.

Les deux parcours ne représentent **ni toutes les trajectoires possibles, ni une borne garantie du résultat**. Le code le précise correctement. Les interruptions et oscillations multiples d’une minute peuvent être importantes pour les stops serrés, les réentrées et les positions opposées.

Correction proposée : replay de transactions horodatées, puis de cotations achat/vente lorsque disponibles ; modèle d’ordres séparé du moteur de signaux ; tests de latence et glissement. Une transaction historique n’est pas une garantie que notre ordre aurait été exécuté au même prix.

Le drawdown actuel est échantillonné à la minute, comme l’indique son nom. Il faut également mesurer les creux de capital et les risques au fil des événements pour analyser des incidents intraminute.

## 5. Funding : proxy adverse des deux côtés

Référence : `range_agents/engine.py`, `_accrue`.

Le coût de financement est un débit continu appliqué à chaque position, indépendamment de son sens. Ce choix est explicitement nommé proxy adverse, et non funding historique.

Il peut servir de scénario de coûts, mais ne suffit pas à comparer fidèlement le hedging au retournement. Correction proposée : taux, heures de règlement, base notionnelle et signe de paiement propres au marché retenu. Conserver aussi un scénario adverse séparé et clairement identifié.

## 6. Pas encore de portefeuille multi-actifs financé

Référence : `range_agents/research.py`, boucles de `sweep` et `holdout` ; `engine.py`, initialisation du capital.

Chaque couple symbole/timeframe repart avec son propre capital fictif. Le pilote correspond à six livres de recherche séparés, et non à un compte de 300 dollars distribué entre six agents.

Correction proposée : chronologie commune, un seul solde, réservations de marge et de risque, déduplication 4H/Daily, contrôle des expositions brutes et nettes. Le classement simultané des signaux doit être causal, jamais choisi après lecture des résultats futurs.

## 7. Univers et données

Référence : `range_agents/data.py`, `download_dataset`, `load_dataset`.

Le collecteur gère une liste statique de symboles et exige un historique complet pour la période. Il ne reconstruit pas un top 50 daté, les introductions/retraits de contrats, ni les changements de taille, de précision ou de symbole.

Les contrôles SHA256, doublons, trous temporels et cohérence OHLC sont déjà présents. Ils doivent être conservés. Ajouter une gestion explicite des périodes où un instrument n’était pas négociable, sans inventer de bougies et sans éliminer silencieusement les actifs qui ont disparu.

## 8. Validation statistique à renforcer

Référence : `range_agents/research.py`, `episode_bootstrap_lower`, `sweep`, `holdout`.

La séparation chronologique, le regroupement par épisode, la conservation des essais et l’absence de promotion automatique sont de bonnes fondations. Le code note lui-même que le bootstrap n’est pas corrigé des essais multiples.

Améliorations proposées : plusieurs validations successives dans le temps, stabilité autour des paramètres retenus, comptabilisation de toutes les variantes explorées, dépendance entre ranges voisins, groupes de dates communes entre actifs, et estimation de l’incertitude. La période finale ne doit pas devenir un jeu de réglage réutilisé sous un autre dossier.

Les paramètres non choisis doivent rester visibles. Les signaux refusés sont journalisés mais n’ont pas encore tous une simulation contrefactuelle autonome permettant de mesurer le résultat de l’occasion refusée.

## 9. Avant toute exécution réelle

Aucun connecteur de trading réel n’est présent. Le mode `research_only` est bloquant et doit le rester tant que les étapes précédentes ne sont pas validées.

La couche future devra tester : identifiants d’ordres persistants, réponses réseau ambiguës, déduplication, redémarrage, reprise d’historique, état réel des positions, exécutions partielles, présence effective des protections, arrondis, minimums, marge, limites API et flux périmés. Les secrets ne doivent pas être accessibles au module de recherche ni apparaître dans les journaux. Les tableaux de bord doivent rester privés.

## Ordre de travail proposé

1. Corriger la faisabilité du pilote, documenter les limites du détecteur et produire des résultats descriptifs fiables.
2. Étendre l’historique utile, séparer les paramètres par stratégie et réaliser les comparaisons chronologiques.
3. Construire le replay événementiel et le portefeuille commun avec les coûts propres au marché.
4. Exécuter une simulation prospective, effectuer des tests de panne, puis seulement examiner une activation réelle validée manuellement.

Ce document décrit un audit et des propositions. Il ne constitue pas une nouvelle version du bot et ne démontre aucune rentabilité.
