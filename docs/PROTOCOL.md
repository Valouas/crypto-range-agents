# Protocole avant étude de rentabilité

1. Obtenir les vrais fichiers et déclarer exactement contrats, canaux, période, trous et précisions. Ne pas confondre transactions historiques et exécutions de nos ordres.
2. Observer les structures dans une période de développement explicitement déclarée ; réserver une période finale différente avant tout examen de ses prix. Ne jamais prétendre non vue une date déjà observée ailleurs.
3. Écrire une hypothèse et une référence : une seule modification, métriques annoncées, critères d'abandon et coûts. Conserver les essais négatifs. Le risque et les frais ne sont pas des variables à optimiser pour rendre le résultat beau.
4. Après accord distinct, utiliser l'ordre du temps et purger les labels/familles débordants. Calibrer le modèle sur une période différente de son entraînement ; tester sa décision ultérieure. Le filtre ne doit pas optimiser le seul taux de réussite.
5. Comparer sur mêmes occasions et sur le compte commun : net calendaire, pertes maximales, périodes sans exposition, utilisation du risque, distribution/concentration. La dépendance à quelques grandes expansions peut être compatible avec l'objectif mais doit être visible.
6. Examiner des réglages voisins et des hypothèses d'exécution dégradées. Réserver, lorsque l'échantillon le permet, des instruments non utilisés pour le choix des filtres. Les événements corrélés entre actifs ne sont pas des confirmations indépendantes.
7. N'utiliser un diagnostic tel que le Deflated Sharpe Ratio que sur une série de rendements et un inventaire d'essais adaptés. La V3 ne calcule pas un DSR à partir d'une liste de trades irréguliers ; aucun bootstrap n'est exécuté en observation seule.
8. Ouvrir une seule fois la période finale, avec une trace écrite. Si ses résultats servent à modifier la stratégie, une autre période réellement nouvelle est requise pour une nouvelle évaluation finale.
9. Toute candidate reste inactive sans validation manuelle. Ni un score élevé, ni des tests de code verts, ni une valeur moyenne estimée positive ne suffisent à activer des ordres réels.
