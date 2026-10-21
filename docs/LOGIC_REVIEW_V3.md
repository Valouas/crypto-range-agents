# Revue de logique — corrections et invariants

Cette revue distingue inspection du code, vérification d'une formule ou d'une barrière, et validation événementielle. La dernière n'a pas été exécutée dans cette livraison.

## Corrections effectivement apportées

**1. Mauvais objectif implicite.** Le modèle V2 ciblait un gain positif et un seuil de 50 %. La V3 sépare probabilité et décision économique ; la cible est nette des coûts. Les frais ne sont pas retranchés deux fois. Une formule scalaire vérifie qu'une probabilité inférieure à 50 % peut avoir une valeur positive si le gain conditionnel est suffisamment supérieur à la perte. Cela n'est pas un backtest.

**2. Sorties imposées par la structure du programme.** La dépendance obligatoire de la partie suiveuse au TP2 empêchait des comparaisons. Les objectifs actifs sont maintenant une liste issue des fractions et le déclenchement du trailing est explicite. Le prix initial et la distance initiale de risque sont conservés lors des exécutions fractionnées.

**3. Mauvaise borne possible pour un stop de réintégration.** Un choix basé seulement sur le sens du trade sélectionnait la borne basse pour un short après réintégration haute. La fonction reçoit maintenant la borne effectivement traversée selon la famille du signal. La référence est figée et l'arrondi défavorable reste contrôlé. Les deux sens ont un contrôle scalaire.

**4. Prix du signal réécrit pendant un retournement.** La nouvelle observation d'exécution possède un champ distinct. Le prix initial, les caractéristiques d'entrée et leur empreinte sont préservés. Une vérification AST empêche la réintroduction de l'affectation fautive dans le moteur.

**5. Comparaison d'un compte partiellement connu.** Une moyenne favorable des trades clôturés ne suffit plus : une période calendaire incomplète/non positive ou des expositions/ordres non résolus rendent la candidature non admissible. La V3 ne force pas une clôture favorable en fin de données. Le calcul de ces états de compte n'a pas été exécuté ici.

**6. Override qui masquait le réglage testé.** Les paramètres d'un timeframe sont résolus dans une copie avant génération des variantes. Les déclarations et les paramètres consommés ne peuvent plus diverger simplement à cause d'un override resté en place.

**7. Profil personnel écrasé par une référence supposée.** Une stratégie de sortie personnalisée est désormais nommée « unchanged » dans la comparaison de base, plutôt que transformée silencieusement en 40/30/30. Les fractions initiales restent intactes.

**8. Grille de recherche réécrite implicitement.** La V2 remplaçait certains réglages pour la réintégration. La V3 respecte la grille explicite et permet une grille par agent. Les paramètres de risque, frais, levier et permission sont exclus du domaine d'optimisation.

**9. Deux candidats indépendants incompatibles.** Les seuils de cycle partagés doivent être cohérents lors de l'assemblage du portefeuille. Un conflit produit `INCOMPATIBLE_SHARED_SIGNAL_PARAMETERS`, pas le remplacement de la première valeur par la seconde.

**10. Approbation contournable par injection.** Les objets de modèle passés au moteur sont reconstruits à partir d'un document dont format, stratégie, empreinte et approbation sont vérifiés. Aucun modèle n'est livré ni activé par défaut.

**11. Fausses preuves de provenance.** Un booléen `synthetic:false` n'est pas une preuve. Les archives et checksums conservés doivent correspondre au contrat/au canal/à la période annoncés ; les tableaux doivent correspondre aux valeurs exactes des sources. Les JSON aggTrades sont comparés à la projection des archives. Les données futures de recherche utilisent aussi cette vérification stricte.

**12. Dates prétendument neuves après un changement de ZIP.** Le registre global suit les dates consultées, pas seulement une empreinte de fichier. Une consultation descriptive expose aussi la période. Les métadonnées V2 d'ouverture sont reprises ; une tentative interrompue n'efface pas la consultation.

## Invariants de stratégie inspectés

Une structure ne devient disponible qu'après ses observations de confirmation. Les événements d'entrée utilisent sa version antérieure figée. Un stop d'excursion utilise l'extrême déjà observé, jamais l'extrême futur de la bougie. Un saut au-delà de toute la boîte n'invente pas une observation intermédiaire à l'intérieur. Une réintégration ne dépend pas de la présence d'un long/short antérieur accepté. Le Daily n'est pas un veto imposé au 4H.

Le catalogue descriptif et le moteur partagent `signals.py`, mais l'observation n'importe pas les composants de portefeuille. Les labels après événement sont séparés des caractéristiques d'entrée. Un seuil relatif à l'ATR/la largeur du range est calculé avec les informations déjà connues et affiché en pourcentage.

## Risque et exécution : limites explicites

Les budgets sont communs et bornés ; les expositions opposées ne libèrent pas automatiquement du risque. Une priorité ne peut regarder des signaux apparus plus tard. À timestamps identiques entre instruments, l'ordre de lecture de l'historique reste une convention documentée ; ce n'est pas un optimum omniscient de portefeuille.

La politique `net_flip` demande la fermeture sur un signal opposé admissible de principe, puis réévalue les contraintes avant de rouvrir. Elle peut donc finir à plat si la deuxième opération devient impossible ; elle ne promet pas un retournement atomique. Les deux opérations supporteraient leurs propres coûts. Aucun ordre réel ne le réalise ici.

Les stops simulés restent des modèles d'exécution, même sur transactions authentiques. Un historique d'aggTrades ne prouve ni la présence de notre ordre dans la file ni son prix de remplissage. Le canal prix de marque, les cotations et les financements ne sont pas fabriqués lorsqu'ils manquent. La configuration d'exécution historique devra être adaptée à l'exchange choisi.

Les fractions sous les minimums d'ordre, les annulations/partial fills, la reprise et le risque actualisé ont été révisés dans le code mais demandent la validation événementielle différée. Des contrôles statiques ne prouvent pas l'absence de toute défaillance d'exécution.

## Limites statistiques

L'estimateur OOD distingue une observation peu connue d'une donnée invalide, sans réécrire le prix. La quantile résiduelle basse affichée n'est pas un intervalle de confiance sur la moyenne. La calibration sur peu d'événements corrélés n'établit pas une probabilité fiable. Les effectifs/dates/familles doivent être examinés avant tout entraînement autorisé.

L'existence d'un registre local ne protège pas contre sa suppression volontaire ni contre des recherches externes non déclarées. Une performance intéressante après beaucoup d'essais reste une sélection ; aucune preuve de rentabilité n'est revendiquée. La référence simple sans apprentissage reste nécessaire.
