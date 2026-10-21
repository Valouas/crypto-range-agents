# Revue statique complémentaire de la V2

Date : 21 septembre 2026. Source : archive V2 fournie dans la conversation. Les lignes ci-dessous correspondent à cette archive et pourront changer après modification. **Aucun test ou simulation n'a été lancé pour cette revue.**

## Ce qui existe déjà : ne pas refaire le même travail

Les modules de la V2 incluent un moteur événementiel, un portefeuille commun, la séparation breakout/réintégration, les réglages par timeframe, les seuils fixes/volatilité/largeur de range, le budget par famille, le réarmement, le ratio coût/stop, les sorties partielles, les excursions MFE/MAE, un témoin de type Donchian et un registre de période finale. Ils comportent aussi des hypothèses d'exécution, pas une reproduction certifiée d'une plateforme réelle. Ne pas présenter ces éléments comme des nouveautés à écrire de zéro.

## Constats et conséquences

### 1. Le filtre appris n'optimise pas directement le gain net

Fichier `range_agents/learning.py`, lignes 39–61 : les labels sont `net_r > 0` (ligne 47), une régression logistique est ajustée (ligne 50), puis le seuil est fixé à `0.5` (ligne 53). `allow()` applique ce seuil (ligne 28).

C'est une classification de résultat positif, pas une estimation de la magnitude du gain/perte. Une stratégie à moins de 50 % de succès peut avoir une espérance positive lorsque ses gains moyens dépassent suffisamment ses pertes moyennes. Un seuil universel de 0,5 n'est donc pas un objectif économique justifié. Il ne s'agit pas d'affirmer que le modèle V2 a déjà éliminé de bons trades : aucun modèle de marché n'est livré comme validé.

### 2. Les deux prises partielles sont obligatoires

Fichier `range_agents/config.py`, lignes 11–15 et fonction `validate` : TP1 et TP2 doivent être positifs, leurs fractions aussi, et leur somme strictement comprise entre zéro et un. Le runner est donc également obligatoire. La référence vaut 40 % / 30 % / 30 %.

Fichier `range_agents/engine.py`, lignes 402–415 : le trailing du runner dépend de `tp2_done`. Autoriser simplement des fractions nulles dans la configuration ne suffit pas à obtenir un véritable mode sans prises partielles. Il faut découpler déclencheur du trailing et réalisation de TP2.

### 3. Le parcours hors du range est peu représenté dans la décision de réintégration

Fichier `range_agents/types.py`, classe `Episode` : direction du cycle et bougie du breakout sont conservées, mais pas l'horodatage exact initial de l'excursion, son extrême hors range ni sa vitesse de retour.

Fichier `range_agents/engine.py`, lignes 122–171 : une réintégration est déclenchée par le retour sous/au-dessus d'un seuil ; les variables du signal décrivent surtout le range, le stop et le dépassement de seuil actuel. Un sweep court et un retour après une longue expansion peuvent donc relever de la même famille de décision, si les autres conditions le permettent.

Les diagnostics ex post dans `diagnostics.py` ne remplacent pas des variables disponibles causalement au moment de la décision. Les utiliser rétroactivement serait incorrect.

### 4. La contrainte de même bougie suit l'horloge

Fichier `range_agents/engine.py`, lignes 132–135 : le cycle change quand `e.ts // TF_MS[r.tf]` n'est plus le bucket de cassure. C'est conforme au choix de l'utilisateur, mais comporte une discontinuité : un aller-retour très court qui traverse minuit UTC n'est pas traité comme un aller-retour plus long restant dans la même journée.

Préserver ce comportement comme référence. Une alternative en durée maximale écoulée exige un mode distinct et un accord ; ce n'est pas une correction à imposer sans discussion.

### 5. Le score de range est une formule choisie manuellement

Fichier `range_agents/ranges.py`, lignes 75–76 : `log1p(window) + log1p(alternations) - drift - shift` favorise notamment la durée et les alternances. Lignes 100–105 : un seul candidat est conservé, au maximum de ce score.

Il n'est pas établi que davantage de touches ou une durée plus longue améliorent la valeur économique. Une banque limitée de candidats horodatés permettra de comparer la sélection sans effacer les candidats non retenus. Les bornes absolues de chaque candidat resteront intactes.

La V2 contient aussi des `min_bars` provisoires (12 en 4H, 7 en Daily) : ce sont des choix d'initialisation et de calcul, pas des minima de rentabilité découverts dans les données.

### 6. Les contraintes de portefeuille existent, pas un classement économique démontré

Fichier `range_agents/engine.py`, lignes 173–244 : limites de positions, exposition, risque réservé et coûts sont déjà contrôlés. Le traitement des propositions est séquentiel. `types.py`, `Event.key()` impose aussi un ordre déterministe entre événements au même timestamp, notamment par symbole.

Cet ordre est nécessaire à la reproductibilité mais n'est pas une preuve d'une meilleure allocation. Toute priorité supplémentaire doit utiliser exclusivement les signaux déjà connus, sans attendre des signaux futurs pour comparer a posteriori le meilleur.

### 7. Moyenne des R par trade et rendement du compte sont distincts

Fichier `range_agents/research.py`, lignes 80–105 et 139–150 : la recherche privilégie la moyenne de R nets, puis la médiane de cette moyenne sur les périodes de validation. Les blocs du bootstrap sont construits à partir des entrées observées ; des blocs sans trade n'y figurent pas.

Le code contrôle ensuite le portefeuille assemblé, mais le classement individuel ne constitue pas une optimisation du résultat calendaire d'un compte unique. Il faut présenter les deux, avec la durée d'immobilisation, les coûts, la baisse maximale et la concentration des gains. Ne pas transformer un petit nombre de très beaux trades en performance régulière présumée.

### 8. Registre de recherches à étendre, pas seulement compteur par exécution

`research.py` conserve les variantes et avertit explicitement que le bootstrap n'est pas corrigé pour les tests multiples. `StudyLedger` empêche une réouverture pour une empreinte de jeu de données et une période qui se chevauchent.

L'identité du jeu est fondée sur toutes les preuves de fichiers (`data.py`, lignes 176–178). Vérifier qu'une nouvelle révision/extension du jeu ne permet pas de considérer des dates déjà consultées comme inédites. La filiation des données et un registre de périodes déjà ouvertes doivent survivre aux nouveaux dossiers, versions, instruments ajoutés et découpages de fichiers. Constat à traiter par une revue et des tests dédiés, non par une garantie déjà acquise.

### 9. Le mode strict « observation seule » doit être explicite

`config.py` n'accepte que `research_only` et `paper_only` dans la V2. `data.py` contrôle les empreintes et la structure, mais le chargeur général n'interdit pas les jeux synthétiques : les démonstrations techniques doivent pouvoir les lire.

Le collecteur autonome impose déjà des données réelles. Il faut ajouter un chemin d'orchestration distinct pour respecter la demande actuelle : aucune création d'ordre, de portefeuille ou de prix fictif, aucun entraînement implicite. Un simple booléen `synthetic: false` ne suffit pas à établir une provenance : vérifier également les justificatifs des fichiers.

## Portée

Ces constats identifient des décisions et protections à améliorer. Ils n'établissent ni une rentabilité actuelle, ni une hausse de rentabilité future. Les vérifications précédemment incluses dans les rapports V2 n'ont pas été répétées ici ; leurs résultats ne remplacent pas les vérifications des changements à venir.
