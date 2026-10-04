# Benchmark : jevnav sur Comet

Google Flights en 9 secondes, vérifié trois fois sur trois.

Ce document mesure le mode ultrafast, c'est-à-dire Jev qui pilote le navigateur de l'utilisateur en CDP direct, et le compare aux autres façons de naviguer depuis Claude. La question tranchée ici : qui doit décider de chaque clic ? Pas le modèle qui raisonne. Le modèle qui raisonne fixe l'objectif ; un modèle de décision joue les pas.

## Méthode

- **Machine.** Un Mac, Comet avec le profil personnel de l'utilisateur (32 onglets ouverts), connexion résidentielle. Mesures du 4 octobre 2026.
- **Pilotage.** jevnav, branché par CDP via le démon browser-harness, Jev `jev-latest` pour chaque décision. Aucun modèle de texte : les valeurs sont fournies par l'appelant.
- **Passages.** Trois par tâche, chacun dans un onglet neuf, par la vraie commande (`bench/run.py`).
- **Vérification.** Indépendante de la réponse de Jev : le script relit la page finale et contrôle l'URL, les champs et les résultats. Un « fini » de Jev ne compte pas tant que la page ne le prouve pas.
- **Temps.** « Navigation » part de la première décision, après le chargement initial de la page, comme dans les mesures publiées par jev-ultrafast. « Total » inclut ce chargement.

Les résultats bruts, avec le statut, les temps, le nombre d'actions et la vérification de chaque passage, sont dans `bench/results/2026-10-04-1702.json`.

## Résultats

| Tâche | Vérifiés | Navigation | Total | Actions |
|---|---|---|---|---|
| Wikipédia : chercher « Alan Turing », ouvrir l'article | 3/3 | 3,0 à 5,4 s (médiane 3,7) | 3,3 à 5,8 s | 2 |
| Google Flights : Zurich → Londres, 20/11/2026, aller simple, résultats affichés | 3/3 | 9,1 à 9,5 s (médiane 9,1) | 9,8 à 10,2 s | 11 |
| Lien : ouvrir la page Dynamic Controls | 3/3 | 0,8 à 0,9 s (médiane 0,9) | 1,2 à 1,5 s | 1 |
| Bouton asynchrone : « Enable », attendre « It's enabled! » | 3/3 | 3,9 s | 4,2 à 4,3 s | 2 |

Le bouton asynchrone prend 3,9 s parce que la page met environ trois secondes à activer le champ. jevnav attend la fin du chargement affiché à côté du bouton avant d'accepter le « fini ».

Une connexion réelle complète aussi le banc : le portail client d'un assureur santé, identifiant puis mot de passe sur deux écrans, remplis par 1Password à l'empreinte. Résultat `done` sur l'accueil connecté en 12,8 s, saisie humaine comprise, zéro caractère tapé par jevnav.

## Comparaison

Mêmes tâches, même Mac, mesurées le même jour avec les autres approches.

| Tâche | jevnav (Comet perso) | jev-ultrafast d'origine (Comet isolé) | Mod jev-browse, navigateur intégré | Mod jev-browse, Comet | Claude seul |
|---|---|---|---|---|---|
| Lien | **0,9 s**, correct | 0,8 à 1,9 s, correct | environ 2,9 s | 5 à 6 s | 27 à 42 s |
| Bouton asynchrone | **3,9 s**, correct | 1,3 à 1,7 s, « fini » prématuré 3 fois sur 3 | environ 6 s | environ 9 s | environ 35 s |
| Wikipédia | **3,7 s** | 3,8 à 4,4 s (avec Haiku pour le texte) | 13,7 s | non mesuré | non mesuré |
| Google Flights | **9,1 s**, 3/3 vérifiés | 9,0 à 10,1 s, 3/3 (avec Haiku pour le texte) | 64 s, inachevé | non mesuré | non mesuré |

Lecture :
- **Face à Claude seul**, jevnav va 30 à 47 fois plus vite sur un lien et environ 9 fois plus vite sur le bouton asynchrone.
- **Face au mod dans Claude Desktop**, l'écart vient du plancher de l'application : chaque clic, frappe ou script coûte 2,2 à 2,5 s. Une tâche de huit actions ne descend donc pas sous 18 s, quel que soit le décideur.
- **Face à jev-ultrafast d'origine**, jevnav tient le même temps sans modèle de texte et corrige le « fini » prématuré. Il ajoute aussi trois choses : il travaille dans le profil réel, il passe les connexions par 1Password et il s'arrête avant toute action irréversible.

## Pourquoi c'est plus rapide

| Étape d'un pas | Claude dans Desktop | jevnav |
|---|---|---|
| Lire la page | 25 à 100 ms | un appel CDP, quelques ms |
| Décider | un tour de Claude, plusieurs secondes | un appel Jev, 0,2 à 0,4 s |
| Agir | 2,2 à 2,5 s (outil + classifieur de sécurité) | un appel CDP, quelques ms |
| Saisir un texte | généré par Claude | valeur fournie, Jev choisit seulement le champ |

Claude ne paie plus qu'un appel d'outil par tâche, contre un tour complet par clic. Côté Jev : un appel par pas, plus un par champ texte. Nous n'avons pas mesuré le coût en euros. Les résultats bruts donnent le nombre d'actions par passage, d'où se déduit le nombre d'appels.

## Limites

- **Échantillon.** Trois passages par tâche, une machine, un réseau. Les écarts de quelques dixièmes de seconde ne sont pas significatifs.
- **Plateforme.** La mise au premier plan et les notifications passent par macOS.
- **Pilotage.** Le clic **Allow** se refait après chaque redémarrage du navigateur, et la case de débogage expose le navigateur aux programmes locaux tant qu'elle reste cochée.
- **Connexions.** Un formulaire dans une iframe d'un autre domaine n'est pas détecté : la connexion se fait alors à la main. Les gardes reposent sur des listes de libellés en anglais, français et espagnol.
- **Valeurs.** Jev peut renvoyer `need_value` sur un champ au libellé ambigu ; l'appelant précise alors la valeur.

Reproduire : `uv run --env-file .env python bench/run.py --runs 3`.
