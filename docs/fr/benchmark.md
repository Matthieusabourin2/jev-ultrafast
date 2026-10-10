# Benchmark : jevnav sur Comet

Google Flights en 6,8 secondes. L'original en met 7,4 sur la même machine.

Ce document mesure le mode ultrafast, c'est-à-dire Jev qui pilote le navigateur de l'utilisateur en CDP direct, et le compare aux autres façons de naviguer depuis Claude. La question tranchée ici : qui doit décider de chaque clic ? Pas le modèle qui raisonne. Le modèle qui raisonne fixe l'objectif ; un modèle de décision joue les pas.

## Duel contre l'original

Un fork n'a de valeur que s'il bat sa source. Nous avons donc fait tourner jev-ultrafast d'origine (commit `1231850`) et jevnav côte à côte, le 10 octobre 2026.

- **Même terrain.** Même Mac, même Comet, même tâche : vols aller simple Zurich → Londres le 20 novembre 2026, une personne. La date de l'original, le 20 septembre, est passée.
- **Même chrono.** Il part de la première décision, après le chargement de la page, comme dans le README de l'original.
- **Même juge.** Un script relit la page finale : page de résultats, aller simple, Zürich, London, date encodée dans l'URL, vols du 20 novembre.
- **Un avantage à l'original.** Il écrit le texte des champs avec un second modèle (DeepSeek), dont nous n'avons pas la clé. Nous le remplaçons par une réponse instantanée.
- **Cinq paires**, en alternance. Le banc est dans `bench/duel/`, les résultats bruts dans `bench/results/2026-10-10-duel.json`.

| | Vérifiés | Médiane | Écart | Appels Jev |
|---|---|---|---|---|
| jev-ultrafast d'origine | 5/5 | 7,42 s | 7,04 à 9,78 s | 17 à 23 |
| **jevnav** | **5/5** | **6,84 s** | **6,77 à 7,14 s** | **13** |

jevnav gagne les cinq paires, avec un quart d'appels Jev en moins et un temps presque constant.

Ce n'était pas acquis. Le premier duel donnait l'inverse : l'original à 7,2-9,4 s, trois fois sur trois, notre fork à 8,7-11,4 s, zéro fois sur trois. Le profil de chaque appel CDP a désigné les coupables, tous ajoutés par nous :

| Poste mesuré | Avant | Après |
|---|---|---|
| Attente de stabilisation avant chaque lecture | 2,2 s par passage | supprimée |
| Pauses (survol, reprise) | 1,4 s | 0,2 s |
| Lecture d'une page de 12 000 éléments | 85 ms | 36 ms (l'original : 21 à 31 ms) |
| Décisions refaites parce que les prix du calendrier chargeaient | 3 à 6 | 0 à 1 |
| Choix de « Zürich, Switzerland » après la saisie de « Zurich » | un appel Jev | aucun, la suggestion nomme le texte tapé |

Le reste vient de règles de main humaine : choisir la suggestion que le site attend, attendre dans la page quand Jev veut attendre, relancer la recherche après la fermeture d'un calendrier.

## Quinze sites réels

Mêmes tâches pour les deux versions, en lecture seule, deux passages chacune, contrôlées sur la page finale (`bench/web.py`, `--arm original` pour l'original). Pour taper les valeurs, l'original reçoit le choix de valeur de jevnav, faute de clé pour son modèle de texte. Le temps inclut le démarrage et le chargement.

| Site | jevnav | Original |
|---|---|---|
| Wikipédia (fr), recherche | 2/2, 3,7 s | 2/2, 4,2 s |
| GitHub, ouvrir un dépôt | 2/2, 9 à 19 s | 0/2, boucle |
| IMDb, fiche d'un film | 2/2, 9,0 s | 2/2, 7,9 s |
| Hacker News, commentaires | 2/2, 2,3 s | 2/2, 2,6 s |
| YouTube, recherche | 2/2, 4,6 s | 2/2, 4,6 s |
| Google Maps, fiche d'un lieu | 0/2 | 0/2 |
| Amazon, premier produit | 2/2, 8,6 s | 0/2, 44 s puis erreur |
| Booking, séjour à Lisbonne | 0/2 | 0/2 |
| Service-public.fr | 2/2, 4,7 s | 2/2, 4,7 s |
| Météo-France, ville | 2/2, 4,7 s | 0/2, « fini » sur l'accueil |
| Doctolib, spécialiste et ville | 2/2, 7,4 s | 0/2 |
| Airbnb, séjour à Porto | 0/2 | 0/2 |
| Décathlon, recherche | 2/2, 4,6 s | 1/2, 4,8 s |
| Google Flights, aller-retour | 2/2, 8,8 s | 2/2, 8,6 s |
| Wikipédia (en), lien coupé sur deux lignes | 2/2, 2,7 s | 0/2, 48 s puis erreur |
| **Total** | **24/30** | **13/30** |

jevnav réussit presque deux fois plus de tâches. Sur les six sites que les deux versions réussissent, les temps se valent : 33,0 s au total contre 32,6 s. La vitesse se gagne sur les parcours longs ; sur une recherche en deux clics, le réseau et le chargement de la page dominent.

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

Mêmes tâches, même Mac, mesurées le 4 octobre avec les autres approches. Pour l'original, le duel du 10 octobre ci-dessus fait foi.

| Tâche | jevnav (Comet perso) | jev-ultrafast d'origine (Comet isolé) | Mod jev-browse, navigateur intégré | Mod jev-browse, Comet | Claude seul |
|---|---|---|---|---|---|
| Lien | **0,9 s**, correct | 0,8 à 1,9 s, correct | environ 2,9 s | 5 à 6 s | 27 à 42 s |
| Bouton asynchrone | **3,9 s**, correct | 1,3 à 1,7 s, « fini » prématuré 3 fois sur 3 | environ 6 s | environ 9 s | environ 35 s |
| Wikipédia | **3,7 s** | 3,8 à 4,4 s (avec Haiku pour le texte) | 13,7 s | non mesuré | non mesuré |
| Google Flights | **9,1 s**, 3/3 vérifiés | 9,0 à 10,1 s, 3/3 (avec Haiku pour le texte) | 64 s, inachevé | non mesuré | non mesuré |

Lecture :
- **Face à Claude seul**, jevnav va 30 à 47 fois plus vite sur un lien et environ 9 fois plus vite sur le bouton asynchrone.
- **Face au mod dans Claude Desktop**, l'écart vient du plancher de l'application : chaque clic, frappe ou script coûte 2,2 à 2,5 s. Une tâche de huit actions ne descend donc pas sous 18 s, quel que soit le décideur.
- **Face à jev-ultrafast d'origine**, jevnav va plus vite sur Google Flights (duel ci-dessus) et réussit presque deux fois plus de sites réels. Il ajoute aussi trois choses : il travaille dans le profil réel, il passe les connexions par 1Password et il s'arrête avant toute action irréversible.

## Pourquoi c'est plus rapide

| Étape d'un pas | Claude dans Desktop | jevnav |
|---|---|---|
| Lire la page | 25 à 100 ms | un appel CDP, quelques ms |
| Décider | un tour de Claude, plusieurs secondes | un appel Jev, 0,2 à 0,4 s |
| Agir | 2,2 à 2,5 s (outil + classifieur de sécurité) | un appel CDP, quelques ms |
| Saisir un texte | généré par Claude | valeur fournie, Jev choisit seulement le champ |

Claude ne paie plus qu'un appel d'outil par tâche, contre un tour complet par clic. Côté Jev : un appel par pas, plus un par champ texte. Nous n'avons pas mesuré le coût en euros. Les résultats bruts donnent le nombre d'actions par passage, d'où se déduit le nombre d'appels.

## Cas difficiles

Quatorze pages locales reproduisent les échecs relevés dans l'usage réel, du 6 au 8 octobre : menus de claude.ai, listes déroulantes de l'URSSAF, formulaires d'entreprise (`examples/hard.py`, `--arm original` pour l'original). Deux passages par version, le 11 octobre 2026.

| Cas | jevnav | Original |
|---|---|---|
| Menu « … » d'une ligne, bouton sans libellé | 2/2, 1,2 s | 0/2, renomme un autre projet |
| Connecteur ajouté par un bouton « + » et une fenêtre | 2/2, 2,0 s | 2/2, 2,3 s |
| Liste native de 400 communes | 2/2, 1,5 s | 0/2, finit sans choisir |
| Liste de comptes personnalisée | 2/2, 1,4 s | 2/2, 1,4 s |
| Cartes de compte cliquables | 2/2, 0,7 s | 0/2, bloqué |
| Formulaire SIRET, code APE, code commune, mail | 2/2, 2,3 s | 2/2, 2,9 s |
| Partage par adresse mail | 2/2, 1,7 s | 2/2, 2,0 s |
| Éditeur de texte riche | 2/2, 1,3 s | 2/2, 1,3 s |
| Boutons visibles au survol seulement | 2/2, 0,8 s | 0/2, bloqué |
| Liste qui défile dans un panneau | 2/2, 1,6 s | 0/2, bloqué |
| Assistant en plusieurs étapes | 2/2, 1,6 s | 2/2, 1,6 s |
| Liste de comptes coupée par le bas | 2/2, 1,3 s | 0/2, 32 s puis erreur |
| Fenêtre qui défile, liste des jours, « Enregistrer » | 2/2, 2,2 s | 0/2, 32 s puis erreur |
| Enregistrer des instructions | 2/2, 1,1 s | 2/2, 1,4 s |
| **Total** | **28/28** | **14/28** |

Sur les sept cas que les deux réussissent, jevnav gagne quatre fois ; les trois autres finissent à moins de 0,05 s d'écart.

Sur le vrai claude.ai, créer un projet, puis enregistrer ses instructions, en un seul appel : les deux versions réussissent, contrôlées en rouvrant le projet. L'original met 6,0 s en 7 actions, jevnav 6,5 s en 8, une attente en trop. Une seule paire : égalité. L'original a tourné avec l'arrêt de jevnav avant tout clic engageant, faute de garde-fou propre sur un compte réel.

Les gardes tiennent en parallèle : sept pages vérifient qu'aucun identifiant n'est tapé (connexion en deux temps, code reçu par SMS, page de vérification) et que les champs ordinaires restent saisissables.

## Limites

- **Échantillon.** Cinq paires pour le duel, deux passages pour les quinze sites, une machine, un réseau. Les écarts de quelques dixièmes de seconde ne sont pas significatifs.
- **Mémoire du profil.** Les tests tournent dans le vrai profil Comet, et les sites se souviennent des passages précédents. Airbnb affiche « Porto, 20–22 nov. » dès l'accueil, et Jev s'arrête là.
- **Échecs communs.** Booking (Jev choisit les deux dates dans le désordre quand des dates sont déjà remplies), Google Maps (le bouton de recherche ne réagit pas sur ce profil) et Airbnb échouent pour les deux versions. jevnav les arrête en 3 à 19 s, au lieu de laisser courir jusqu'au plafond de 60 actions.
- **Plateforme.** La mise au premier plan et les notifications passent par macOS.
- **Pilotage.** Le clic **Allow** se refait après chaque redémarrage du navigateur, et la case de débogage expose le navigateur aux programmes locaux tant qu'elle reste cochée. S'il manque, jevnav répond `allow_needed` en 45 s au lieu d'attendre sans fin.
- **Connexions.** Un formulaire dans une iframe d'un autre domaine n'est pas détecté : la connexion se fait alors à la main. Les gardes reposent sur des listes de libellés en anglais, français et espagnol.
- **Valeurs.** Jev peut renvoyer `need_value` sur un champ au libellé ambigu ; l'appelant précise alors la valeur.

## Qui lance jevnav : Haiku ou Opus

Même tâche jevnav, déléguée à un sous-agent de Claude Code, aller-retour complet : Haiku 5.5 en 7,6 et 9,9 s, Opus en 12,2 s (un relevé aberrant à 191 s écarté). Le sous-agent coûte surtout son démarrage, environ 78 000 jetons de contexte, pour 2 à 3 s de navigation. Un appel isolé se lance donc directement depuis la conversation ; une navigation à plusieurs relances gagne à passer par un sous-agent Haiku. Deux paires seulement : à confirmer.

Reproduire : `uv run --env-file .env python bench/run.py --runs 3`, `bench/web.py` et `bench/duel/`.
