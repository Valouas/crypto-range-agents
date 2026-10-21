# Plan d'améliorations : logique, rentabilité recherchée et protocole

## Règle de décision

Distinguer **correction logicielle**, **capacité de recherche** et **hypothèse de stratégie**. Une fonctionnalité implantée n'est pas automatiquement utile ni validée. Aucun pourcentage n'est optimal avant une évaluation autorisée sur données adaptées. La collecte et les analyses de prix observés peuvent avancer maintenant ; la reconstruction de trades exige un nouvel accord.

## P0-00 — Observation réelle seule et collecte utilisable

**But.** Passer de plusieurs ZIP séparés à un parcours clair : archives réelles → contrôles → catalogue de structures et franchissements observés. Aucun portefeuille fictif dans ce parcours.

**Travail.** Ajouter un mode d'observation explicitement distinct des modes de la V2, vérifier la compatibilité des schémas du collecteur et du chargeur, afficher un tableau de couverture par instrument/type/jour. Conserver les ZIP d'origine, leur checksum fournisseur, les dates de téléchargement, l'unité d'horodatage, les règles d'agrégation et la filiation des transformations. Refuser données synthétiques, provenances inconnues, trous silencieux et mélange spot/perpétuel. Ne pas exiger des champs absents en les inventant.

**Collecte progressive.** Les bougies 4H/Daily servent au catalogue causal des structures. Pour l'intrabougie, collecter les transactions d'intervalles calendaires continus déterminés à l'avance. Une alternative ciblée autour des ranges doit couvrir tous les épisodes admissibles, pas seulement les cassures qui ont ensuite réussi. Fusionner les intervalles qui se chevauchent ; garder assez d'historique pour les variables avant signal. Cette collecte ciblée seule ne permet pas de calculer la performance d'un compte 24/7 sans une couverture adaptée.

**Acceptation.** Sur un vrai lot reçu, attester la provenance, compter les trous et les bornes temporelles, comparer le schéma et les prix agrégés à la source à précision documentée. En absence d'historique fin, ne pas inférer l'ordre des événements depuis OHLC. Le catalogue mentionne `DONNEES_INSUFFISANTES`. Pas de démo de remplacement.

## P0-01 — Objectif économique du filtre, pas seuil de victoire à 50 %

**Problème.** `net_r > 0` suivi de `p >= 0.5` ignore l'amplitude asymétrique des résultats.

**Proposition.** Préserver une référence sans modèle. Après autorisation d'étudier des trades historiques hypothétiques, comparer une estimation simple du R net attendu et une décomposition probabilité de gain / gain conditionnel / perte conditionnelle. Une régression régulière ou des groupes simples peuvent suffire au départ ; pas de réseau neuronal obligatoire.

**Décision.** Tenir compte du résultat net moyen, des pertes extrêmes, de l'incertitude et du budget de risque existant. Ne jamais transformer une probabilité en certitude. Avec des gains/pertes déjà nets, ne pas soustraire les frais une seconde fois. Vérifier la calibration sur des données ultérieures distinctes de l'entraînement et du choix de seuil. Les partitions doivent être chronologiques ; les défauts de validation croisée aléatoire d'une bibliothèque ne sont pas adaptés automatiquement.

**Acceptation.** Un signal à moins de 50 % de succès ne doit pas être refusé mécaniquement si son modèle de valeur est favorable ; inversement, un taux de réussite élevé ne suffit pas. La mesure sur signaux acceptés doit être accompagnée d'une comparaison sur les mêmes occasions, du total net et du compte partagé. Peu d'exemples ou mauvaise calibration → abstention ou référence déjà approuvée, jamais risque accru.

## P0-02 — Comparer les sorties sans préjuger du gagnant

**Proposition.** Rendre configurables des fractions non négatives dont la somme vaut un. Conserver la référence à deux prises partielles, permettre une seule prise partielle et une sortie uniquement suiveuse comme variantes de recherche. Comparer aussi break-even désactivé / conditionnel, sans imposer une remontée rapide.

**Implémentation.** Découpler activation du trailing et `tp2_done`. Prévoir un déclencheur explicite et causal, en pourcentage ou en R initial immuable. Assurer la couverture de la quantité restante, la précision en lots et l'absence de réutilisation de liquidité fictive. Un stop ne peut être exécuté au meilleur prix historique après constatation d'un recul.

**Acceptation.** À entrées et risque initial identiques, rendre visibles le résultat net, la baisse maximale, les coûts et la part des excursions conservée. Séparer la dépendance aux quelques gros gains d'une preuve d'instabilité : une stratégie de continuation peut volontairement être asymétrique. Aucun seuil de runner n'est validé à ce stade.

## P0-03 — Une réintégration décrite par son parcours déjà observé

**Proposition.** Ajouter à chaque épisode l'heure exacte de franchissement, l'extrême depuis le franchissement, la distance maximale hors range, la durée hors range et une mesure de vitesse de retour disponible au signal. Conserver les événements même si l'ordre breakout est refusé : l'agent contraire ne dépend pas de l'existence d'une position antérieure.

**Hypothèse.** Un dépassement court puis rejet et un retour après une expansion durable ne sont peut-être pas des occasions équivalentes. Les étiqueter séparément permet de le vérifier. Les seuils de classification sont provisoires et évalués sans lire le futur.

**Temporalité.** Conserver `same_structure_candle=True` comme référence. Étudier séparément une fenêtre en temps écoulé, sans l'appeler SFP de même bougie ni la substituer au choix de l'utilisateur. La même logique d'entrée immédiate reste possible : toutes les informations utilisées doivent déjà être connues au moment de la réintégration.

**Acceptation.** L'extension du fichier de marché après le signal ne modifie pas ses caractéristiques enregistrées. Les extrema utilisés s'arrêtent exactement à l'instant du signal. Tous les refus et ordres non exécutés restent distingués. Les trajectoires postérieures ne servent qu'à des diagnostics ultérieurs.

## P1-04 — Candidats multiples, approche du niveau et espace avant structure voisine

**Travail.** Conserver une banque bornée de ranges admissibles au lieu de ne journaliser que le gagnant d'un score arbitraire. Les bornes de chaque candidat restent son maximum/minimum absolu ; aucun remplacement silencieux par des quantiles. Dédupliquer les familles et limiter le coût de calcul.

**Variables proposées, calculées avant franchissement.** Compression près de la borne, position du prix dans le range, amplitude de l'approche récente normalisée, profondeur des retours précédents, distance au prochain swing majeur déjà confirmé hors range. Représenter l'imbrication de ranges pour différencier la cassure d'une petite boîte interne de la sortie de l'ensemble.

**Attention.** Une résistance historique n'est pas une barrière certaine. Une absence de niveau détecté n'est pas « espace infini ». Davantage de touches peut être favorable ou défavorable ; ne pas inscrire le sens de l'effet dans le score par conviction. Ne pas imposer la tendance Daily comme veto d'un signal 4H et ne pas faire attendre le franchissement initial.

**Acceptation.** Une variable ou filtre à la fois, même base d'occasions, méthode de référence inchangée. Les fenêtres, conditions et identifiants sont disponibles avant le signal et versionnés. Les observations inconnues restent inconnues.

## P1-05 — Stops ancrés sur l'invalidation, affichés en pourcentage

**Proposition.** Comparer la distance fixe depuis l'entrée avec des ancres structurelles : borne cassée et marge pour un breakout ; extrême réellement observé de l'excursion et marge pour une réintégration. Les modes volatilité et largeur de range déjà présents restent des références possibles, pas des nouveautés.

**Contraintes.** Le stop est calculé à partir du prix d'entrée et de l'ancre réellement connue. Sa distance est ensuite affichée en pourcentage. Si la distance requise n'est pas compatible avec le risque ou les tailles minimales, diminuer la quantité ou refuser. Ne pas resserrer artificiellement le stop pour afficher un meilleur rapport gain/risque, ni l'éloigner après coup pour éviter une perte. Le levier n'est pas un paramètre à optimiser.

**Acceptation.** Ancre figée et traçable, risque et coûts recalculés selon prix/tailles, protections conservées après exécution partielle. Ne pas déplacer arbitrairement l'entrée à la borne si le marché a déjà sauté le seuil.

## P1-06 — Allocation causale d'un petit compte et budget par événement

**Proposition.** Comparer le fonctionnement séquentiel existant à une priorité préétablie parmi des signaux déjà disponibles, fondée sur leur valeur estimée, coûts, risque et exposition déjà ouverte. Utiliser la corrélation de rendements observée avant signal uniquement comme diagnostic/contrôle expérimental, sans supposer tous les alts identiques ni parfaitement indépendants.

**Contrainte d'immédiateté.** Ne pas retarder une entrée pour regarder quels autres signaux apparaîtront ensuite. À timestamps identiques, documenter l'ordre conventionnel si l'ordre de réception réel est absent. Préparer les priorités avant le franchissement si nécessaire. Ne pas donner toujours le capital au premier symbole alphabétique sans en mesurer l'effet.

**Compte partagé.** Comparer le net total calendaire, les périodes sans trade, les pertes maximales, l'utilisation du capital et la concentration des gains. Un signal opposé ne doit pas automatiquement annuler le risque réservé : des positions opposées peuvent se fermer à des instants différents. Hedging/retournement restent des politiques comparables à enveloppe identique.

**Acceptation.** Aucun changement de budget global appris automatiquement, aucun bénéfice créé par agrégation de comptes indépendants. La performance de chaque agent et celle du compte réel potentiel sont séparées. Toute allocation adaptative reste bornée et approuvée manuellement.

## P1-07 — Modèle incertain, marché nouveau, vrais extrêmes

**Proposition.** Ajouter un état explicite « contexte hors du domaine appris » et la date d'expiration d'une version. Les outils comme FreqAI documentent un contrôle de distance aux observations d'apprentissage [S3]. Cela peut servir de diagnostic plutôt que d'augmenter le risque sur une prédiction extrapolée.

**Attention au but de la stratégie.** Une expansion exceptionnelle peut être un événement recherché. Ne pas supprimer automatiquement toutes les observations extrêmes ni les remplacer par des prix moyens. Distinguer erreur de donnée établie, vrai mouvement extrême et incertitude du modèle. Les cas rejetés restent archivés pour mesurer les occasions manquées.

**Acceptation.** Si le contexte est inconnu : politique préapprouvée d'abstention ou référence indépendante déjà approuvée. Aucun réentraînement/activation autonome. Les seuils de distance et la calibration proviennent de données d'entraînement/validation séparées. Les diagnostics ne garantissent pas la valeur future.

## P1-08 — Protocole de recherche et tests multiples

**Proposition.** Tenir un registre global des hypothèses, expériences et périodes déjà consultées à travers les versions de code/données. Évaluer la plus-value de chaque composant par retrait/ajout isolé. Prévoir une évaluation chronologique du compte assemblé et des instruments laissés de côté lorsque la taille du jeu le permet. Les signaux d'une même phase de marché et les variantes d'un même range ne sont pas des preuves indépendantes.

**Choix statistique.** Le Deflated Sharpe Ratio traite les effets de sélection parmi de multiples essais et la non-normalité [S4]. C'est un diagnostic possible lorsque les séries et hypothèses s'y prêtent, pas un label automatique « stratégie rentable ». Ne pas l'appliquer naïvement à une liste de trades irréguliers ou déclarer tous les essais indépendants. Le calcul doit tenir compte de la base de rendement calendaire, des périodes sans exposition et des dépendances pertinentes.

**Contrainte actuelle.** Aucun bootstrap, permutation ou backtest ne sera lancé dans le mode observation seule. Documenter d'abord ce protocole ; les expériences quantitatives de rentabilité attendent l'autorisation.

**Acceptation.** Paramètres et métriques annoncés avant consultation de la période finale. Résultats négatifs conservés. Un changement de jeu par ajout de fichiers ne rend pas de nouvelles les dates déjà utilisées. Résultat autorisé : « données insuffisantes », « aucun gain mesurable », ou « candidate à examiner », jamais « rentabilité garantie ».

## Ordre conseillé

1. P0-00 maintenant : données réelles, observation seule, catalogue causal.
2. P0-01 à P0-03 : préparer les corrections et capacités de comparaison, versions inactives.
3. P1-04 / P1-05 : quelques hypothèses prix/structure, pas une accumulation d'indicateurs.
4. P1-06 à P1-08 : évaluation du compte, gouvernance et protocole avant toute comparaison de performance.
5. Exécution d'expériences de rentabilité seulement après nouveau consentement, couverture de données suffisante et définition transparente des hypothèses d'ordres.

## À ne pas ajouter maintenant

Pas de martingale, grille de rattrapage, levier appris, cent modèles par actif, renforcement automatique après une série de gains, IA conversationnelle dans le chemin critique d'exécution, filtres payants ou dizaines d'indicateurs. Ne pas acheter de données ni choisir un exchange définitif sans décision de l'utilisateur.
