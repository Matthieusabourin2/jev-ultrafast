# Installer jevnav

Un clic coûte 0,3 seconde, pas 2,5.

C'est l'écart entre un pas décidé par Jev et piloté en CDP direct, et un pas joué par Claude dans un navigateur intégré. jevnav fait naviguer Jev dans votre propre navigateur (Comet ou Chrome), avec vos sessions ouvertes et votre 1Password. Claude ne fait plus que deux choses : donner l'objectif et les valeurs à saisir, puis lire le résultat.

Ce tutoriel couvre macOS et se suit en quinze minutes si la clé TypeSafe est déjà prête.

## Ce qu'il faut avant de commencer

| Élément | Pourquoi | Vérification |
|---|---|---|
| macOS | la mise au premier plan et les notifications passent par `osascript` | `sw_vers` |
| Comet ou Chrome 144+ | le navigateur piloté, avec votre profil | `chrome://version` |
| uv | installe Python et les dépendances | `uv --version` |
| Une clé API TypeSafe | Jev décide chaque pas | console TypeSafe |
| 1Password et son extension dans le navigateur | remplit les identifiants à votre place | l'icône 1Password dans la barre d'outils |

Aucun modèle de texte n'est nécessaire. Les valeurs à saisir viennent de l'appelant, en général Claude.

## 1. Cloner et installer

```bash
git clone https://github.com/Matthieusabourin2/jev-ultrafast.git ~/jev-ultrafast
cd ~/jev-ultrafast
uv sync
```

Créez le fichier `.env` à la racine du dépôt, que git ignore déjà, avec la clé et le modèle Jev :

```bash
cat > .env <<'EOF'
TYPESAFE_API_KEY=votre_clé_typesafe
TYPESAFE_MODEL=jev-latest
EOF
chmod 600 .env
```

Si vous rangez la clé dans 1Password, injectez-la sans l'afficher : `op read "op://Coffre/Élément/champ"` redirigé vers le fichier.

## 2. Ouvrir le navigateur au pilotage

jevnav se branche sur le navigateur déjà ouvert, sans le relancer.

1. Dans Comet, ouvrez `chrome://inspect/#remote-debugging`.
2. Cochez **Allow remote debugging for this browser instance**. L'adresse `127.0.0.1:9222` s'affiche.
3. Au premier lancement de jevnav, le navigateur demande **Allow remote debugging?** : cliquez **Allow**.

Ce clic se refait après chaque redémarrage du navigateur. Tant que la case reste cochée, n'importe quel programme local peut piloter votre navigateur et lire vos sessions : décochez-la dès que vous n'utilisez plus jevnav.

Pour Chrome à la place de Comet, ajoutez `JEVNAV_APP="Google Chrome"` dans `.env`, guillemets compris : sans eux, uv ignore la ligne sans prévenir.

## 3. Installer la commande

Un petit script dans `~/.local/bin` rend `jevnav` disponible depuis n'importe quel dossier et charge `.env` à chaque appel.

```bash
mkdir -p ~/.local/bin
cat > ~/.local/bin/jevnav <<'EOF'
#!/bin/zsh
cd ~/jev-ultrafast && exec uv run --quiet --env-file .env jevnav "$@"
EOF
chmod +x ~/.local/bin/jevnav
```

Vérifiez que `~/.local/bin` est dans votre `PATH`, puis lancez un premier essai :

```bash
jevnav --url https://en.wikipedia.org/wiki/Main_Page --goal "Search Wikipedia for Alan Turing and open his article" --values '{"query":"Alan Turing"}' --close
```

La commande rend une seule ligne JSON. Sur ce test, attendez `"status": "done"` en quatre à six secondes, avec l'adresse de l'article d'Alan Turing dans le champ `url`.

## 4. Lire le résultat

| Statut | Ce qui s'est passé | Ce que fait l'appelant |
|---|---|---|
| `done` | l'objectif est atteint et visible | lire `url`, `title`, `text` |
| `need_value` | un champ attend une valeur absente de `--values` | ajouter la valeur pour `field`, relancer avec `--target` |
| `confirm` | le prochain clic est irréversible (payer, envoyer, supprimer, réserver, accepter…) | demander à l'utilisateur, relancer avec `--target` et `--confirm "<libellé>"` |
| `login_timeout` | un formulaire de connexion attend toujours | l'utilisateur remplit avec 1Password, puis relance avec `--target` |
| `in_progress` | le budget de temps est écoulé | relancer avec `--target` |
| `refused` | une clé de `--values` ressemble à un secret | retirer la clé ; la connexion passe par 1Password |
| `blocked`, `error` | Jev ne trouve plus d'action utile, ou une erreur technique | lire `error`, changer d'approche |

L'onglet reste ouvert après chaque appel. `--target` reprend le même onglet avec l'historique des actions, sans `--url`. `--close` ferme l'onglet quand le statut est `done` ou `blocked`.

## 5. Se connecter avec 1Password

jevnav ne tape jamais un identifiant, un mot de passe ou un code. Quand il voit un formulaire de connexion, il vous passe la main et attend que la connexion aboutisse :

1. il met le navigateur au premier plan et place le curseur dans le champ identifiant ;
2. il affiche une notification macOS ;
3. vous remplissez avec 1Password (empreinte), puis vous cliquez le bouton de connexion, écran par écran ;
4. dès que le formulaire disparaît, il reprend la tâche.

L'attente dure 120 secondes par défaut (`--login-wait`), 30 secondes depuis le chat de Claude Desktop. Les clés de `--values` qui ressemblent à un secret (`password`, `email`, `login`, `code`…) sont refusées avant toute navigation.

## 6. Brancher Claude Code

Ajoutez cette règle dans `~/.claude/CLAUDE.md` pour que chaque session Claude Code passe par jevnav :

```markdown
## Navigation web : jevnav d'abord
Toute tâche dans mon navigateur passe par `jevnav` (Bash) : `jevnav --url <url> --goal "<objectif>" --values '{"champ":"valeur"}'`.
Statuts : need_value → ajouter la valeur et relancer avec --target ; confirm → me demander, puis --confirm ;
login_timeout → je remplis avec 1Password, puis relancer avec --target. Jamais d'identifiant dans --values.
```

Pour interdire le navigateur intégré de Claude Desktop, ajoutez la règle de refus dans `~/.claude/settings.json` :

```json
{ "permissions": { "deny": ["mcp__Claude_Browser"] } }
```

Fusionnez cette ligne avec vos permissions existantes plutôt que de remplacer le fichier.

## 7. Brancher le chat de Claude Desktop

Le chat de Claude Desktop n'a pas de terminal. jevnav y arrive sous forme de serveur MCP. Ajoutez ce bloc dans `~/Library/Application Support/Claude/claude_desktop_config.json`, sous `mcpServers`, en remplaçant le chemin :

```json
"jevnav": {
  "command": "/opt/homebrew/bin/uv",
  "args": ["run", "--quiet", "--directory", "/Users/vous/jev-ultrafast", "--extra", "mcp",
           "--env-file", "/Users/vous/jev-ultrafast/.env", "python", "-m", "jev_ultrafast.mcp_server"]
}
```

Quittez puis rouvrez Claude Desktop. L'outil `jevnav` apparaît dans la liste des connecteurs du chat. Chaque appel s'arrête de lui-même avant 45 secondes et rend l'onglet à reprendre, pour rester sous le délai d'attente du client.

Le chat ne lit pas `CLAUDE.md`. Pour qu'il choisisse jevnav de lui-même, ajoutez une phrase dans **Réglages > Profil > Préférences** sur claude.ai, par exemple : « Pour toute navigation dans mon navigateur, utilise l'outil jevnav. »

## 8. Vérifier l'installation

```bash
uv run pytest -q tests                                       # tests unitaires, sans navigateur
uv run --env-file .env python examples/guards.py             # gardes de sécurité, dans le vrai navigateur
uv run --env-file .env python bench/run.py --runs 3          # banc de performance, voir benchmark.md
```

`examples/guards.py` sert trois pages locales et vérifie qu'aucun caractère n'arrive dans un champ de code ou d'identifiant, et qu'un code postal reste saisissable.

## Dépannage

| Symptôme | Cause | Correction |
|---|---|---|
| La commande ne rend rien pendant une minute | le navigateur attend le clic **Allow** | cliquer **Allow** dans la fenêtre du navigateur |
| `Model connection failed` | l'API TypeSafe est injoignable | vérifier le réseau et la clé, relancer |
| `blocked` immédiat sur une application web | la page s'affiche lentement | relancer avec `--target` ; jevnav attend déjà jusqu'à 10 s une page vide |
| `login_timeout` sans notification | le formulaire est dans une iframe d'un autre domaine | se connecter à la main, puis relancer avec `--target` |
| `confirm` sur un bouton anodin | son libellé figure dans la liste des actions irréversibles, ou il n'a pas de libellé lisible | relancer avec `--confirm "<libellé>"` |
| `ModuleNotFoundError: jev_ultrafast` | macOS a caché le fichier `.pth` de `.venv` (vu dans `~/Documents`) et Python 3.14 l'ignore | préfixer la commande par `PYTHONPATH=.`, ou cloner hors de `~/Documents` |
