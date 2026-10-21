# Range Agents V3 — collecte authentique et observation causale

> Guide français conservé depuis l’archive du 21 septembre 2026. Pour les vérifications de la préparation GitHub du 22 octobre 2026, voir [PUBLICATION_NOTES.md](docs/PUBLICATION_NOTES.md).

Version 3.0.0. Mise à jour du code V2 ; aucun résultat de rentabilité V2/V3 n'est livré comme preuve.

**La version démarre en observation seule.** Elle collecte et contrôle des archives publiques, repère des structures sur les bougies clôturées 4H/Daily et catalogue leurs franchissements sur des transactions réellement reçues. Elle ne crée alors ni compte fictif, ni position, ni rendement de trading.

Les améliorations de recherche sont codées, mais les commandes de backtest, entraînement et paper trading sont verrouillées. Aucun connecteur d'ordres réels n'existe. Aucun modèle appris n'est livré. Aucune donnée de marché artificielle n'a été générée pour cette mise à jour.

## Installation Windows

Extraire **tout** le ZIP dans un nouveau dossier, sans écraser la V2. Python 3.11 ou plus récent est requis. Le développement a été vérifié sous Linux/Python 3.13.5, pas sous Windows.

| Lanceur | Action |
|---|---|
| `01_INSTALLER.bat` | Crée `.venv`, installe les dépendances figées et affiche le diagnostic. Nécessite l'accès à PyPI. |
| `02_CONTROLER_CODE_SANS_SIMULATION.bat` | Compile, vérifie les configurations et exécute seulement les contrôles autorisés. |
| `03_VOIR_PLAN_COLLECTE.bat` | Affiche les périodes et archives demandées ; ne télécharge pas. |
| `04_COLLECTER_STRUCTURES_REELLES.bat` | Demande les archives 4H/Daily, conserve ZIP et checksums. |
| `05_COLLECTER_TRANSACTIONS_REELLES.bat` | Demande le premier lot d'aggTrades configuré. Ne pas lancer deux collectes simultanément. |
| `06_OBSERVER_DONNEES_REELLES.bat` | Vérifie les sources puis produit le catalogue causal, sans ordres. |

Sous Linux/macOS, depuis la racine :

```bash
python -m venv .venv
# Linux/macOS : source .venv/bin/activate
# Windows : .venv\Scripts\activate
python -m pip install -r requirements.txt
python scripts/validate_static.py
python -m range_agents collect --task plan
python -m range_agents collect --task structures --data data/reel
python -m range_agents collect --task transactions --data data/reel
python -m range_agents observe --config configs/observation.json --data data/reel --out runs/observation
```

`requirements-optional.txt` concerne les expériences ultérieures ; il n'est pas nécessaire au catalogue de prix. Ces commandes n'activent aucun entraînement.

## Périmètre demandé, et non déjà téléchargé

Le plan repris du collecteur authentique demande BTCUSDT, ETHUSDT et SOLUSDT, futures USD-M Binance : bougies du 1er janvier 2021 au 31 août 2026 inclus (408 archives mensuelles demandées), transactions agrégées des 1er et 2 janvier 2025 (6 archives journalières demandées). Ce n'est ni un univers historique top 50, ni une couverture transactionnelle de toutes ces années.

La disponibilité de chaque archive doit être vérifiée. Le contrôle réseau de cette livraison a échoué à la résolution DNS ; **aucune archive réelle n'est incluse**. Les valeurs de stratégie présentes dans les JSON sont des hypothèses de départ, pas des réglages optimaux.

Le collecteur reprend les archives complètes déjà vérifiées. Une collecte interrompue peut exporter seulement les archives authentiques reçues ; les canaux absents restent absents. Aucune interpolation ne comble un trou. Une erreur et les périodes manquantes apparaissent explicitement.

## Sorties de l'observation

`runs/observation/` contient, lorsque des données suffisantes ont réellement été reçues :

| Fichier | Contenu |
|---|---|
| `observation.json` | Statut, provenance, nombres effectivement observés, limites. |
| `coverage.csv` | Couverture des bougies et des fichiers transactionnels reçus. |
| `missing_transaction_days.csv` | Jours demandés non collectés, sans inférence intrabougie. |
| `candidates.jsonl.gz` | Banque bornée de ranges et candidat de référence, dates de disponibilité. |
| `observed_events.jsonl.gz` | Franchissements/réintégrations observés ; caractéristiques figées au signal. |
| `observed_paths_EX_POST.jsonl.gz` | Parcours réellement observé après le signal ; jamais injecté rétroactivement dans les caractéristiques d'entrée. |
| `observation.html` | Rapport descriptif local. |

En absence de données : diagnostic `DONNEES_INSUFFISANTES`, pas de remplacement par une démonstration. Des bougies seules permettent de décrire des structures, pas de déterminer l'ordre exact des événements à l'intérieur d'une bougie.

## Logique préservée

Les stratégies breakout et réintégration sont distinctes, chacune configurable en 4H et Daily. Les structures utilisent seulement les bougies terminées, mais leur franchissement n'attend pas la clôture de la bougie en cours. Une borne est figée avant utilisation et reste le maximum/minimum absolu de la période retenue, mèches incluses.

La référence de réintégration exige la même bougie de structure ; c'est un signal anticipé, pas un SFP déjà confirmé par sa clôture. La variante en durée écoulée est explicitement séparée et inactive. Pas de filtre de volume ajouté. Pas de veto Daily obligatoire sur le 4H.

Un franchissement observé peut être catalogué même si une stratégie n'aurait pas pu accepter l'ordre. L'observation d'un rejet n'est pas un PnL ni la preuve qu'une position aurait été exécutée.

## Capacités de recherche préparées mais inactives

Objectif économique en R net attendu au lieu d'un seuil de réussite à 50 % ; sorties à deux, une ou aucune prise partielle ; déclenchement indépendant du stop suiveur ; ancre structurelle du stop ; description causale de l'excursion ; banque de ranges imbriqués et approche des bornes ; attribution causale d'un capital commun ; abstention du modèle, calibration et expiration ; registre commun des hypothèses, tentatives et périodes déjà vues.

La référence reste sans modèle. Les alternatives ne s'activent pas parce qu'elles existent dans le code. Les objets de modèles V2 sont rejetés ; une nouvelle version nécessitera un apprentissage autorisé et une approbation liée à son empreinte.

`runtime_policy.json` autorise uniquement `observation`, `public_collection`, `static_checks`. Ce dispositif évite les lancements accidentels : ce n'est pas une protection contre une personne qui modifie volontairement les fichiers locaux. Il ne faut pas le déverrouiller sans nouvel accord du propriétaire.

## Migration et Codex

`AGENTS.md` et `PROMPT_DEPART_CODEX.md` sont à la racine. Lire aussi `docs/VALIDATION_V3.md` et `docs/LOGIC_REVIEW_V3.md` avant de changer le code. Les fichiers V2 de données authentiques du collecteur autonome sont acceptés seulement après vérification de leurs archives sources. Les anciens fichiers de démo, snapshots de portefeuille V2 et modèles V2 ne sont pas migrés silencieusement.

Pour une configuration V2 personnelle, produire un nouveau fichier :

```bash
python -m range_agents migrate-config --input chemin/config_v2.json --out configs/ma_configuration_v3.json
```

Les réglages stratégiques compatibles sont conservés, mais le mode revient en observation seule et les chemins de modèles sont désactivés. Les champs incompatibles provoquent une erreur au lieu d'une adaptation hasardeuse.

## Contrôles et statut

Lire `docs/VALIDATION_V3.md` pour les preuves et leur périmètre exact. La suite standard est `tests_static`, pas une certification du moteur complet. Les tests d'acceptation dynamiques sont différés et demandent un accord distinct et de véritables fichiers de marché. Aucun pourcentage, niveau de performance ou taux de réussite n'est validé par cette livraison.
