# Validation événementielle différée — non exécutée

La permission actuelle ne permet aucun scénario de marché ni ordre reconstitué. Ces obligations sont enregistrées pour une étape ultérieure autorisée. `tests_dynamic/test_genuine_data_acceptance.py` contient quatre tests différés utilisant exclusivement un chemin vers des archives authentiques fournies extérieurement ; il n'engendre aucun historique. Les conditions manquantes donnent un test ignoré, pas une réussite.

## Acceptation des vraies données

Contrôler un ZIP/checksum réellement reçu, la projection de chaque valeur et les horodatages UTC ; faire échouer un fichier altéré sans corriger ses prix ; mesurer les trous et les jours sans événements. Vérifier le catalogue visuellement sur des ranges identifiés par le propriétaire. La période observée doit être inscrite au registre avant analyse.

## Causalité

Comparer le résultat sur un préfixe d'historique authentique avec le même préfixe suivi de données ultérieures. Les bornes déjà publiées et les caractéristiques déjà enregistrées doivent être identiques. Contrôler la cassure intrabougie, la réintégration dans la même bougie et la variante écoulée, la frontière UTC, le réarmement, l'absence de prix intermédiaire inventé et le suivi d'une réintégration après refus du breakout.

## Positions et risque — accord de reconstitution nécessaire

Exercer un trade réellement déclenché par l'historique, une exécution fractionnée, l'annulation du reste et la conservation de la protection ; vérifier les deux sens, TP multiples, un seul TP, runner seul, BE net de coûts, arrondis de lots, ancre figée et absence d'élargissement du risque. Si le lot ne contient pas un cas, le marquer non exercé plutôt que le déclarer validé.

Contrôler les limites communes avec ordres en attente, positions opposées, signaux 4H/Daily concomitants, trous de flux, reprise SQLite, prix de marque obsolète, prix d'exécution éloigné et ordre de sortie partiellement rempli. Le portefeuille doit conserver ses identités comptables à chaque événement. Tester la priorité sans lire un autre instrument plus tardif. Documenter l'ordre conventionnel des événements de même timestamp.

## Modèles et recherche — accord d'entraînement distinct

Vérifier les partitions chronologiques train/calibration/validation, les familles partagées et les labels qui débordent ; normalisation du train uniquement. Mesurer sur mêmes occasions la référence non filtrée et la filtrée. Vérifier l'expiration, le contexte inconnu, la calibration et la signature d'approbation. Ne pas apprendre sur les labels EX_POST pour décider à leur heure antérieure.

Évaluer séparément la robustesse des paramètres, les périodes sans trade, la baisse maximale, le coût et la concentration. Consigner toutes les variantes. Le compte assemblé doit être évalué séparément des comptes spécialisés. Aucun test final déjà regardé ne peut être rebaptisé inédit avec un nouveau nom de fichier.

## Non inclus dans ce protocole immédiat

Le test d'un connecteur d'ordres natifs, des erreurs réseau d'exchange et de la vérification de stops réels exige une autre étape et un environnement autorisé. Aucun passage au compte réel n'est automatique.
