# Instructions du propriétaire — Range Agents V3

## Permission actuelle

L'utilisateur autorise les modifications de code, les contrôles statiques/scalaires, la collecte publique de vraies données et l'observation de celles-ci. Il a expressément refusé les simulations à ce stade.

Ne pas lancer de démonstration, de parcours de marché fabriqués, de backtest, d'optimisation, de bootstrap, de paper trading, d'entraînement de modèle ou d'ordre réel sans nouvel accord spécifique. Ne pas modifier `runtime_policy.json` pour rendre un test vert. Ne jamais qualifier d'exécution réelle un ordre reconstitué sur un historique authentique.

Les quatre tests différés de `tests_dynamic` ne sont pas validés dans cette livraison. Les anciens tests V2 sont archivés séparément ; leur ancien décompte ne prouve rien pour la V3.

## Commandes autorisées

`python scripts/validate_static.py`, `python -m range_agents doctor`, `check-config`, `collect --task plan|structures|transactions|verify`, `verify-data`, `observe` et `registry-summary`. `pytest` cible par défaut uniquement `tests_static`.

Utiliser `configs/observation.json`, pas un ancien lanceur de démo. En absence de données véritables, produire un diagnostic et ne pas générer une série de remplacement. Les tests de métadonnées et de formules scalaires ne doivent pas être présentés comme une validation financière ou un scénario de marché exécuté.

## Invariants métier

Ranges horizontaux majeurs, bornes extrêmes exactes figées avant événement. 4H et Daily indépendants. Entrée au franchissement intrabougie, pas d'attente systématique de clôture/retest. Réintégration intrabougie distinguée du SFP confirmé ; référence dans la même bougie. Pas de filtre de volume ; pas d'ajout de dizaines d'indicateurs. Les paramètres en pourcentage sont en unités pourcent : 0.10 signifie 0,10 %.

Les caractéristiques du signal sont copiées, horodatées et empreintées ; les observations postérieures sont dans un fichier EX_POST distinct. Pas d'accès au futur, pas de comblement de trous. L'absence d'une résistance n'est pas un espace connu infini.

Le modèle estime une valeur nette avec incertitude, pas seulement une probabilité supérieure à 0,5. Aucun levier ou risque ne peut être appris/augmenté. Toute version est approuvée manuellement. Une ancre structurelle trop lointaine doit réduire la taille/refuser, pas être resserrée arbitrairement. Deux positions opposées ne s'annulent pas dans le risque réservé.

## Organisation du code

`signals.py` est partagé par observation et moteur pour éviter deux définitions divergentes. `observation.py` ne doit jamais importer le simulateur, le calcul de PnL ou l'apprentissage. `geometry.py` contient les formules scalaires. `policy.py` bloque les opérations non autorisées avant création d'un portefeuille. `governance.py` conserve globalement les dates vues, indépendamment des fichiers et des symboles.

## Critères de fin et communication

Petits changements révisables, tests du périmètre autorisé, rapport exact de ce qui a été exécuté et de ce qui ne l'a pas été. Mettre à jour la matrice d'implémentation, le registre des décisions et le manifeste de livraison. Ne pas annoncer une amélioration de rentabilité sans une expérience autorisée et correctement identifiée. Une erreur ou une donnée insuffisante est un résultat acceptable.

## Prochain travail

Priorité : réussir la collecte d'un lot authentique dans l'environnement de l'utilisateur, contrôler les octets/projections/couverture, puis afficher les vrais ranges et franchissements observés. Ne pas commencer par réentraîner le modèle. Ne pas supposer un exchange réel définitivement choisi ; aucun identifiant de trading n'est requis.
