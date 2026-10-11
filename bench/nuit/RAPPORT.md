# Nuit du 11 octobre 2026 : cinquante essais mesurés pour rendre jevnav plus rapide et plus fiable

Cinquante essais, dix-neuf changements gardés.

Chaque changement est passé par la même chaîne : une hypothèse écrite, la porte de non-régression, un duel en paires alternées contre la version sans le changement, puis la relecture par un agent neuf. Flights, les 15 sites, les cas difficiles et les sites jamais réglés ont été mesurés sur le commit `fe9a223`. Trois correctifs de sécurité sont venus après (jusqu'à `5696562`) : sur cette tête finale, seuls la porte et les tests unitaires ont été rejoués. Ils comparent la branche à `main`, c'est-à-dire jevnav d'hier soir, et à l'original jev-ultrafast.

## Le résultat

| Banc (même Mac, même Comet, paires alternées) | Avant | Après |
|---|---|---|
| Google Flights contre l'original, 5 paires | original 6,93 s, 16 appels Jev | **jevnav 5,87 s, 10 appels**, 5 paires gagnées sur 5 |
| Google Flights aller-retour, contre jevnav d'hier, même horloge | 7,99 s | 6,52 s |
| 15 sites réels × 3 passages | 35/45 réussis | **43/45** (Maps, Booking, Airbnb passent) |
| Temps sur les 11 sites réussis des deux côtés | 58,2 s | 53,2 s (−8,5 %) |
| 14 cas difficiles d'origine × 3 | 42/42, 24,8 s | 42/42, 22,3 s (−10 %) |
| 6 nouveaux pièges reproduits cette nuit × 3 | 6/18 | 18/18 |
| Réserve de 16 sites jamais réglés × 2 | 12/32 | 16/32 |
| dont les 12 sites jamais touchés de la nuit | 10/24 | 14/24 (indice, à confirmer) |

Sur l'ensemble du duel contre `main`, la branche gagne 57 paires sur 82 (test du signe, p < 0,001).

Sur la tête finale `5696562`, la porte passe à 38 sur 38 au premier passage, sans relance. Sur la nuit, 21 portes ont été franchies, et 7 d'entre elles ont eu besoin d'une relance sur un site instable (Doctolib, GitHub, Flights, Airbnb, Amazon). Le « 100 % » s'entend donc relances comprises, sauf pour la porte finale.

## Ce qui a changé

**Les bandeaux cookies sont refusés, plus vite.** Refus formulés en phrase, refus caché au second niveau (OneTrust), flèche décorative : jevnav refuse sans demander à Jev. Quand un site n'offre que « accepter ou payer », jevnav s'arrête et le dit (`reason: consent_or_pay`).

**Les calendriers ne coûtent plus d'appels.** Le jour demandé est cliqué directement, l'arrivée avant le départ, le mois est rattrapé quand le profil garde une ancienne recherche, puis « Done » est cliqué. C'est l'essentiel du gain sur Flights.

**Les impasses s'arrêtent vite.** Un bouton qui tourne en boucle sort des choix de Jev. Une recherche ignorée par le site (Google Maps) est relancée, et « fini » est refusé tant que les dates choisies n'ont pas été soumises.

**Les pages muettes parlent.** Libellés écrits en CSS, tiroir modal vide qui masquait toute la page (Leroy Merlin), loupe sans nom à côté d'un champ de recherche.

**La sécurité est plus stricte.** Un bouton-icône (« ➤ », « + ») demande désormais confirmation : avant, un « ➤ » d'envoi de message était cliqué sans confirmation, et le défaut existe aussi sur `main`. La relecture finale a fermé trois autres raccourcis :
- « Refuser la commande » était pris pour un refus de cookies ;
- le « Decline » d'une invitation qui parle de RGPD était cliqué ;
- le raccourci du « Done » de calendrier pouvait cliquer « Apply ».

Ces trois cas sont maintenant couverts par des tests.

## Ce que les échecs nous apprennent

La latence de Jev ne dépend presque pas de la taille de la requête. Seize variantes rejouées hors ligne (texte de page coupé, libellés raccourcis, historique réduit, JSON compact, gzip, 40 éléments au plus) restent autour de 260 ms, au bruit près. Le temps se gagne en supprimant des appels, pas en allégeant chacun.

Les réglages d'attente sont du bruit : six variantes, aucun gain au-dessus de 3 %, et parfois une réussite perdue.

## Comment lire le compte

- 31 expériences jouées de bout en bout dans Comet : 19 gardées, 12 rejetées.
- 16 rejeux hors ligne de requêtes Jev enregistrées : toutes rejetées.
- 2 sur l'outillage du banc (contrôle des garde-fous, temps de démarrage).
- 1 sans effet observable (e42 : aucune page enregistrée n'était sans champ).
- Les rejeux e9 à e14 sont une seule expérience en six variantes. Compté honnêtement, cela fait 45 expériences distinctes, sous l'objectif de 50.
- e33 (connexion préchauffée) est gardée sous le seuil de 3 % : gain significatif de 1,7 %, sans coût ni risque.

La réserve n'est vraie que pour 12 sites, et leur gain tient à trois d'entre eux (Darty, Goodreads, Castorama) sur deux paires : c'est un indice de généralisation, pas une preuve. J'ai débogué en direct sur Leroy Merlin, TheFork, Larousse, AlloCiné, Marmiton, Trainline, npm, Hugging Face, LDLC et 20 Minutes. Seuls les 12 autres mesurent la généralisation.

## Tes sites, d'après l'historique de Comet

Neuf tâches en lecture seule sur les sites que tu fréquentes le plus d'après l'historique de Comet (90 derniers jours) : recherche, messagerie, stockage de documents, claude.ai, réservation. Un passage par version, dans tes sessions déjà ouvertes, sans saisie d'identifiant ni envoi. La liste des tâches reste privée (`perso.py`, exclu du fork public).

| | `main` | Branche de nuit |
|---|---|---|
| Réussis | 5/9 | 6/9 (la recherche Google passe) |
| Temps sur les 5 réussites communes | 23,0 s | 20,6 s (−10 %) |

Les deux versions échouent sur trois tâches : une page de réglages de claude.ai, un site où ton compte ouvre un tableau de bord au lieu de la recherche, et une compagnie aérienne.

## Deux relectures de plus sur la sécurité

Un relecteur neuf a repassé les correctifs de la relecture finale. Il a trouvé une régression : les bandeaux allemands et espagnols (« Alle Cookies ablehnen », « Rechazar todas las cookies ») n'étaient plus refusés, et « Alle akzeptieren » pouvait être cliqué sans confirmation. C'est corrigé (commit `aa23a91`), avec trois fuites mineures : « Tout bloquer » est reconnu comme refus, « Refuser : supprimer » demande confirmation, et le raccourci « Done » de calendrier ne prend plus « Terminer » ni « Fertig ». Ce correctif a lui-même été relu, et deux trous sont apparus. Un « Bloquer » seul, celui qui bloque un contact sur Telegram ou WhatsApp, passait sans confirmation. « Tout bloquer » et « Block all » passaient aussi, sur n'importe quelle page. Seuls « Bloquer les cookies » et « Block all cookies » restent des refus (commits `27c95ab` et `5696562`). Dix verbes irréversibles ont été ajoutés (effacer, quitter, leave, löschen, blockieren, melden, senden, entfernen, bloquear, denunciar), et refuser une proposition ou une mission sur Malt demande désormais confirmation.

Un risque reste ouvert, et il existait déjà sur `main` : un « Refuser » ou un « Decline » nu, dans une invitation d'agenda ou de Teams, est cliqué sans confirmation alors qu'il prévient l'organisateur. Le corriger demande de lire aussi la boîte autour du bouton.

## Ce qui reste

- **Shadow DOM** (MDN, Rotten Tomatoes) : jevnav ne voit pas les contrôles des composants web. C'est un chantier pour une autre nuit, qui touche à la lecture de page et à l'exécuteur.
- **Murs « accepter ou payer »** (AlloCiné, 20 Minutes, Marmiton) : la décision t'appartient, site par site.
- **Hugging Face, LDLC** : la loupe sans nom reste en confirmation, parce que le filtre anti-invitation est volontairement prudent.
- **BBC, Cdiscount, France Info, arXiv, BlaBlaCar** : ces sites échouent des deux côtés et n'ont pas été étudiés cette nuit.

## Avant de fusionner

- La branche `nuit-2026-10-11` est poussée sur le dépôt privé, et rien n'est sur `main`.
- Les journaux de nuit contiennent des URL de ton profil (paramètres Google, pages claude.ai). Ils sont exclus du fork public par `.publicignore`.
- La commande `jevnav` utilise ce qui est extrait dans `~/Documents/jev-ultrafast`. J'ai remis `main`, donc tu tournes sur la version d'hier tant que la branche n'est pas fusionnée.

Le journal complet, une ligne par expérience, est dans `bench/nuit/ledger.jsonl` ; le tableau ci-dessous en est tiré.

## Les cinquante essais

| # | Expérience | Verdict | Mesure |
|---|---|---|---|
| e01 | Refus de cookies en phrase | gardée (bout en bout) | 2 cas locaux 0/4 → 4/4 ; porte complète 29/29 ; Marmiton et Leroy Merlin reproduits ; faille « Refuser et supprimer » trouvée en relecture et corrigée |
| e02 | Libellés dessinés en CSS | gardée (bout en bout) | cas local 0/2 → 2/2 ; porte 30/30 hors garde-fous (frappes extérieures, voir commit) ; AlloCiné : affiche désormais « J'accepte » / « Je m'abonne » (mur payant, arrêt correct) |
| e00 | Contrôle des garde-fous fiable | gardée (outil) | 7/7 avec frappes parasites signalées à part ; aucune fuite de valeur |
| e03 | Démarrage plus rapide (uv, imports) | rejetée (outil) | mesuré : 0,22 s hors navigation (uv 0,06 s, imports 0,25 s en partie recouverts), sortie 0,05 s : rien à gagner |
| e04 | Refus des cookies direct et en deux niveaux | gardée (bout en bout) | consent_layer 0/2 → 3/3 ; consent_rien 2,6-3,6 s → 2,3 s ; consent_prefere 3,4 s → 2,3 s ; Trainline réel : bandeau refusé ; porte 31/31 ; relecture : contexte resserré + « Refuser le devis » à confirmer |
| e05 | Boucle sur un même bouton | gardée (bout en bout) | Trainline : 94,8 s (limite) → arrêt en 5,5 s ; porte 31/31 (github instable, échec par l'ancien détecteur à 3 recherches) |
| e06 | Valeurs non saisies avant une recherche | rejetée (bout en bout) | cas local « remembered » : 3/3 des deux côtés (2,51 → 2,26 s, bruit) ; Flights 4 paires sans perte (8,55 → 7,97 s, bruit) ; Trainline toujours bloqué : aucun gain de réussite démontré, code retiré, cas de test gardé |
| e07 | Pas de relecture avant décision | gardée (bout en bout) | 9 tâches × 5 paires : 32/45 victoires, somme des médianes 33,65 → 32,86 s puis 35,44 → 33,89 s (≈ −3 %), p ≈ 0,003 ; porte 32/32 |
| e9-text3000 | Requête Jev allégée : Texte de page plafonné à 3000 car. | rejetée (rejeu) | Rejeu hors navigateur de 45 requêtes réelles (Flights, Amazon, Doctolib, YouTube) : bytes identiques (texte déjà court) ; latence 262 → 263 ms. La latence ne dépend pas de la taille (≈ 260 ms). |
| e10-text1500 | Requête Jev allégée : Texte de page plafonné à 1500 car. | rejetée (rejeu) | Rejeu hors navigateur de 45 requêtes réelles (Flights, Amazon, Doctolib, YouTube) : latence 258 → 262 ms ; accord 43/45. La latence ne dépend pas de la taille (≈ 260 ms). |
| e11-notext | Requête Jev allégée : Sans texte de page | rejetée (rejeu) | Rejeu hors navigateur de 45 requêtes réelles (Flights, Amazon, Doctolib, YouTube) : latence 268 → 264 ms (−0,3 Ko) ; accord 40/45 : la décision change. La latence ne dépend pas de la taille (≈ 260 ms). |
| e12-label60 | Requête Jev allégée : Libellés d'éléments plafonnés à 60 car. | rejetée (rejeu) | Rejeu hors navigateur de 45 requêtes réelles (Flights, Amazon, Doctolib, YouTube) : latence 269 → 260 ms médiane, 268 → 270 ms moyenne : rien. La latence ne dépend pas de la taille (≈ 260 ms). |
| e13-noelements | Requête Jev allégée : Éléments non répétés dans l'état (seulement dans les questions) | rejetée (rejeu) | Rejeu hors navigateur de 45 requêtes réelles (Flights, Amazon, Doctolib, YouTube) : latence 260 → 257 ms ; accord 32/45 : la décision se dégrade. La latence ne dépend pas de la taille (≈ 260 ms). |
| e14-hist5 | Requête Jev allégée : Historique limité aux 5 dernières actions | rejetée (rejeu) | Rejeu hors navigateur de 45 requêtes réelles (Flights, Amazon, Doctolib, YouTube) : latence 266 → 260 ms ; accord 43/45 : rien de mesurable. La latence ne dépend pas de la taille (≈ 260 ms). |
| e15 | Connexion Jev préchauffée | rejetée (bout en bout) | 3 × 3 appels : premier appel 278-312 ms à froid, 216-322 ms après préchauffage (qui coûte lui-même 260-300 ms) ; gain ≤ 50 ms, sous le bruit |
| e17 | Attente automatique après une recherche qui change d'adresse | rejetée (bout en bout) | 9 tâches × 3 paires : 18/27 victoires, somme des médianes 47,67 → 47,12 s (−1,2 %, sous le seuil de 3 %). Sur Flights, Jev demande encore « Wait » après l'attente automatique : les résultats arrivent par vagues après le calme du DOM. |
| e16 | Saisie directe d'un champ nommé par une clé | gardée (bout en bout) | 13 tâches × 3 paires : aller-retour Flights +40 % (dates tapées) → dates exclues ; 9 tâches × 3 paires : 20/27 victoires, 42,75 → 39,99 s (−6,5 %), formulaire métier −31 % ; météo et service-public re-mesurés 4 paires : 8/8 victoires. Relecture : libellé entier exigé (« name » ≠ « Company name »). |
| e18 | Jour de calendrier choisi sans Jev | gardée (bout en bout) | Flights, aller-retour, formulaire pré-rempli × 5 paires : 11/15 victoires, 17,36 → 15,42 s (−11 %), aller-retour −21 % ; porte 32/32. Relecture : cellules de date seules, jour collé au mois, « mar. » = mardi. |
| e19 | « Done » du calendrier sans Jev | gardée (bout en bout) | Flights + aller-retour × 5 paires : 8/10 victoires, 13,87 → 13,29 s (−4,2 %) ; porte 32/32. |
| e20 | Recherche ignorée relancée (Google Maps) | gardée (bout en bout) | Maps 0/2 (et 0/2 pour l'original) → 13/13 sur la version finale (5+3+5), après deux variantes rejetées (relance unique 3/5 ; condition sur le texte 1/4). Coût sur recherche en place : 0 (requête répétée dans les résultats). Ajouté à la porte. |
| e21 | Calendrier à plage : arrivée puis départ | gardée (bout en bout) | Booking : échec depuis le début → 3/3 (réserve : après le 1er succès, le profil garde 20-22 nov.) ; Airbnb : 2/2 puis 3/3 avec e22-e23. Ajoutés à la porte. |
| e22 | Pas de « fini » avant la recherche des dates | gardée (bout en bout) | Airbnb : échec dans la porte e21 (dates choisies, pas de recherche) → 2/3, puis 3/3 avec e23 ; porte 35/35. |
| e23 | Bouton en boucle retiré des choix de Jev | gardée (bout en bout) | Airbnb (« Filtres » × 4) : 3/3 ensuite, sans repasser par le chemin « Filtres » : effet propre non isolé ; porte 35/35, aucun cas difficile cassé. |
| e24 | Modèle Jev épinglé (jev-1.13.0) | rejetée (rejeu) | Rejeu de 90 requêtes alternées : médiane 259 → 254 ms (−2 %, bruit), accord 89/90. Épingler figerait aussi les mises à jour de Jev : pas de gain qui le justifie. |
| e25 | Plafond d'attente dans la page 1000 → 1600 ms | rejetée (bout en bout) | 7 tâches × 3 paires : 10/20 victoires, somme 37,69 → 38,42 s (+2 %) ; Flights −11 % mais Amazon +22 % ; un échec Doctolib côté B. Rejeté. |
| e26 | Attente initiale dans la page 300 → 200 ms | rejetée (bout en bout) | 7 tâches × 3 paires : 11/20 victoires, somme −3,3 % mais un échec Flights côté B (résultats jugés trop tôt) : la fiabilité passe avant. Rejeté. |
| e27 | Rendre la main au DOMContentLoaded | rejetée (bout en bout) | 8 tâches × 5 paires : 25/38 victoires, ≈ −3 %, 40/40 réussites contre 38/40 ; mais la porte échoue sur Booking (2/2 : recherche lancée avant que le site ait restauré dates et voyageurs, URL sans dates). Rejeté. |
| e28 | Bouton sans effet caché après 2 clics | rejetée (bout en bout) | Booking toujours en boucle (« Nombre de personnes… » × 4). Défaut relevé par la relecture : masquage par libellé, qui cacherait aussi les autres « Ajouter » ou « Supprimer » d'une liste. Rejeté sans duel. |
| e29 | Requête Jev compressée (gzip) | rejetée (rejeu) | L'API refuse : HTTP 415 (Content-Encoding non pris en charge). |
| e30 | JSON compact (sans espaces) | rejetée (rejeu) | 45 requêtes alternées : médiane 257 → 270 ms, accord 41/45 (même contenu : c'est le bruit de Jev). Aucun gain. |
| e31 | Champs vides retirés de la requête Jev | rejetée (rejeu) | 45 requêtes : médiane 268 → 250 ms mais moyenne 265 → 263 ms (bruit), accord 42/45 ≈ niveau du bruit. Gain non démontré. |
| e32 | Critères de cible réduits à la ligne d'élément | rejetée (rejeu) | 45 requêtes : médiane 258 → 251 ms, moyenne 264 → 258 ms (−2 %), accord 42/45. Sous le seuil de 3 %. |
| e33 | Connexion Jev préchauffée pendant le chargement | gardée (bout en bout) | Premier appel à froid 302 ms contre 235 ms préchauffé (8 processus de chaque). Duel isolé 8 tâches courtes × 4 paires : 22/32 victoires, −1,7 %, p = 0,025. Exception assumée à la règle des 3 % : gain significatif, coût et risque nuls. |
| e34 | Loupe sans nom d'une recherche qu'on vient de taper | gardée (bout en bout) | Larousse : confirm → réussi ; nameless_search (local) 2/2 ; Hugging Face reste en confirm (son champ dit « users », filtre d'invitation volontairement prudent) ; LDLC reste en confirm. Garde nameless_invite : confirm, rien envoyé. Porte 38/38. |
| e35 | Navigation de mois dans un calendrier à plage | gardée (bout en bout) | Booking après booking_other : échec → 3/3 (porte e34, essai, porte e36). Relecture : sens modulo 12 sans année, « Suivant » nu retiré (bouton d'assistant). |
| e36 | Sécurité : bouton-icône = bouton inconnu | gardée (bout en bout) | Faille trouvée par la garde nameless_send : la base envoie le message (« ➤ » cliqué), la nouvelle version s'arrête en confirm, rien envoyé. row_menu et hover_rows (« ⋯ » qui ouvre un menu) intacts. Porte 38/38. |
| e37 | Attente des suggestions tardives 0,8 → 0,5 s | rejetée (bout en bout) | 7 tâches × 3 paires : 12/20 victoires, p = 0,25, un échec Airbnb côté B (suggestion manquée). Rejeté. |
| e38 | Historique Jev réduit à 2 actions | rejetée (rejeu) | 45 requêtes : latence identique (261 → 260 ms), accord 35/45, sous le bruit (41/45) : Jev décide autrement. Rejeté. |
| e39 | Libellés coupés à 40 caractères | rejetée (rejeu) | 45 requêtes : 259 → 265 ms, accord 40/45. Aucun gain. |
| e40 | Texte de page coupé à 500 caractères | rejetée (rejeu) | 45 requêtes : 249 → 243 ms (−2 %), moyenne identique, accord 41/45. Sous le seuil. |
| e41 | Consignes des questions retirées | rejetée (rejeu) | 45 requêtes : 263 → 248 ms (−6 %) mais accord 11/45 : Jev ne décide plus pareil. Rejeté net. |
| e42 | Question de saisie retirée quand rien ne se tape | rejetée (nul) | Sans effet mesurable : aucune des 45 pages enregistrées n'était sans champ ; latence 258 → 258 ms. Note : la variante hist0 du rejeu était fausse ([-0:] garde tout) et n'est pas comptée ; elle donne le bruit de Jev à requête identique : 41/45. |
| e43 | « Regarder encore » 0,6 → 0,4 s | rejetée (bout en bout) | 8 tâches × 3 paires : 15/24 victoires, somme 38,94 → 39,47 s (+1,4 %), p = 0,15. Aucun gain. |
| e44 | Attente des pages vides 0,5 → 0,2 s | rejetée (bout en bout) | 7 tâches × 3 paires : 8/15 victoires, p = 0,5 ; Google perso 0/3 côté B contre 2/3 (instabilité Google confirmée ensuite sur la base : 1/2). Aucun gain. |
| e45 | Touche Entrée quand le bouton de recherche reste inerte | rejetée (bout en bout) | Cas local inert_button : Entrée lance bien la recherche (résultats affichés), mais Jev ne conclut pas (reclique puis « Open Rechercher » et BLOCKED), 0/5 ; sur Google, le cas ne s'est pas reproduit (4/4 sans lui). Rejeté ; piste : Jev ne lit pas le texte de résultat apparu sur place. |
| e46 | Modale vide ignorée | gardée (bout en bout) | Leroy Merlin : 2 → 29 actions, échec → réussi (7,0 s). Porte 38/38, gardes OK (modal.html inchangé). |
| e48 | Refus de cookies avec flèche décorative | gardée (bout en bout) | TheFork : échec (attentes puis défilement) → 2/2. Porte verte. |
| e49 | Défilement automatique sur BLOCKED : 8 → 4 | rejetée (bout en bout) | 8 tâches × 2 paires : sur les réussites, 4/9 victoires, somme +19 % (Rotten Tomatoes réussi plus lentement) ; aucune réussite gagnée. Rejeté. Au passage, Darty et Rotten Tomatoes réussissent maintenant (2/2 et 1-2/2) sur la base du jour. |
| e50 | Mur « accepter ou payer » signalé | gardée (bout en bout) | AlloCiné et 20 Minutes : confirm avec reason consent_or_pay (Marmiton : bloqué ce passage-là). Le comportement reste l'arrêt : accepter des cookies demande l'accord de Matthieu. Porte 38/38. |
| e51 | Éléments offerts à Jev plafonnés à 40 | rejetée (rejeu) | 90 requêtes alternées : 260 → 259 ms, accord 85/90 (au niveau du bruit). Aucun gain : la latence de Jev ne dépend presque pas de la taille de la requête (vu aussi en e30-e32, e38-e41). |
