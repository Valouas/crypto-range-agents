# Compte rendu de validation V3

> Rapport historique de développement, conservé depuis l’archive V3 du 21 septembre 2026. Les anciens fichiers de journalisation sous `docs/evidence` ont été exclus de la préparation GitHub. Les vérifications de la version préparée sont indiquées dans [PUBLICATION_NOTES.md](PUBLICATION_NOTES.md).

## Verdict limité

**123 contrôles de schémas, formules scalaires, permissions et métadonnées ont réussi.** Le code a été compilé et les 23 modules applicatifs importés sans erreur constatée. Le lanceur de validation a également été exécuté.

Ce résultat n'est **ni** un backtest, **ni** une mesure de rentabilité, **ni** une validation complète du cycle des ordres. Les mécanismes événementiels ajoutés ont été revus mais n'ont pas été rejoués sur une trajectoire de marché. Ils restent à valider avec un accord distinct.

## Ce qui a été exécuté

- Compilation du package et du collecteur ; vérification de syntaxe des quatre tests différés (sans les exécuter).
- Validation des quatre configurations V3, toutes en observation seule, modèle désactivé.
- `python scripts/validate_static.py` : uniquement la suite autorisée.
- `python -m pytest tests_static -q` : 123 succès lors de la passe finale de développement ; voir JUnit et sortie texte.
- `doctor`, `check-config`, `collect --task plan` : diagnostic et plan seulement, pas de collecte de remplacement ni d'expérience.
- Import des 23 modules, sans appel d'un moteur de marché.
- Vérification d'accès à un checksum public : échec DNS explicite, conservé dans `network_check.json`.

Les tests utilisent des configurations, intervalles de métadonnées, valeurs arithmétiques scalaires et objets bloqués avant création de compte. Ils ne génèrent pas une série de cours ou un fichier de résultats de trading. Les contrôles du registre utilisent des bases temporaires de test, pas de vraies expériences.

Une attente de type tuple/liste dans le test de fusion d'intervalles a d'abord échoué ; l'assertion a été alignée sur le format public du composant (listes sérialisables). Les contrôles de régression ajoutés ensuite couvrent notamment la borne de réintégration, les overrides et les conflits de seuils.

## Périmètre couvert

Les fractions et l'activation du trailing, la copie et validation des overrides, les paramètres non finis, les permissions, l'objectif économique scalaire, la géométrie des stops et les seuils d'horloge sont contrôlés. Les sources inattendues, modes réels, données sans preuve et anciennes versions de modèle sont refusés. Le registre protège la continuité des dates vues, les réservations finales et l'historique des essais. La commande de backtest est testée comme refusée AVANT lecture d'un fichier de données inexistant.

Le compteur de 123 est le nombre de cas collectés par pytest, pas un pourcentage de couverture de branches ni 123 preuves indépendantes de qualité financière. Les anciens 164 tests V2 ne sont pas utilisés comme attestation V3.

## Ce qui n'a pas été exécuté

Aucune démonstration artificielle. Aucun backtest. Aucun calcul de PnL reconstitué. Aucune optimisation. Aucun bootstrap. Aucun entraînement ou calibration de modèle. Aucun paper trading. Aucun ordre réel. Aucun appel nécessitant des clés de trading.

Les quatre tests de `tests_dynamic` sont différés, non comptés comme réussites. Les scénarios supplémentaires nécessaires sont détaillés dans `DYNAMIC_VALIDATION_REQUIRED.md`. Leur état est « non exécuté », pas « passé parce que bloqué ».

## Données réelles

L'essai de téléchargement d'un checksum Binance public a renvoyé `URLError: <urlopen error [Errno -3] Temporary failure in name resolution>`. La source visée et l'heure exacte sont dans le diagnostic. **Zéro archive réelle récupérée et aucun historique inclus.** La conversion/observation de vrais fichiers doit encore être contrôlée dans un environnement où le téléchargement fonctionne.

Le plan indique 408 fichiers mensuels de structures demandés et six fichiers journaliers d'aggTrades, pas autant de fichiers effectivement téléchargés. Les canaux de carnet, mark price, financement et règles historiques ne sont pas supposés présents.

## Environnement et reproduction

Développement : Linux, Python 3.13.5 ; numpy 2.3.5, pandas 2.2.3, requests 2.32.5, pytest 9.0.2. Les versions exactes sont dans `docs/evidence/environment.json`. Les lanceurs Windows sont fournis mais n'ont pas été exécutés sous Windows. Aucun test de packaging wheel ni test réseau de plateforme d'ordres n'a été réalisé.

Depuis la racine extraite : `python scripts/validate_static.py`. Cette commande ne nécessite pas de données de marché et ne déverrouille pas le moteur. Une installation de dépendances peut nécessiter l'accès au réseau.

## Livraison et contrôle indépendant

La V2 d'origine est conservée ; la V3 est dans un nouveau dossier. Le ZIP de livraison est accompagné d'une empreinte SHA-256 et d'un manifeste interne. Le rapport de contrôle de l'extraction indépendante est joint sous `verification_archive_v3.json` à côté du ZIP ; il décrit la passe réellement exécutée après création de l'archive, sans modifier le ZIP.

## Conclusion

La revue a permis de corriger les points de logique identifiés et de préparer toutes les familles d'améliorations du plan. Les contrôles autorisés passent. **La prochaine preuve attendue est l'observation vérifiée d'un lot authentique, puis une validation événementielle expressément autorisée.** Aucun réglage n'est déclaré optimal et aucun gain de rentabilité n'est établi.
