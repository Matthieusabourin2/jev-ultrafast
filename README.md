# jevnav : Jev Ultrafast dans votre propre navigateur

> Fork de [browser-use/jev-ultrafast](https://github.com/browser-use/jev-ultrafast). Le README d'origine, en anglais, reste disponible en bas de page.
> Documentation : [installation](docs/fr/installation.md) · [benchmark](docs/fr/benchmark.md).

Google Flights rempli en 9 secondes, vérifié trois fois sur trois.

## Ce que c'est

Jev Ultrafast d'origine ouvre son propre onglet, laisse [Jev de TypeSafe](https://docs.typesafe.ai/introduction) choisir chaque pas et confie la saisie de texte à un petit LLM. Ce fork ajoute `jevnav`, une commande qui fait tourner la même boucle dans le navigateur que vous utilisez déjà : votre profil Comet ou Chrome, vos sessions ouvertes, votre 1Password.

Le partage des rôles tient en une ligne. Claude, ou tout autre appelant, fixe l'objectif et fournit les valeurs à saisir ; Jev décide chaque clic en 0,2 à 0,4 seconde. Le modèle qui raisonne planifie, le modèle de décision agit.

## Comment ça marche

```
appelant ──objectif + valeurs──▶ jevnav ──CDP──▶ votre profil Comet ou Chrome
                                   │  Jev choisit l'opération et l'élément suivants
                                   │  Jev choisit quelle valeur fournie va dans quel champ
                                   │  formulaire de connexion → onglet au premier plan, curseur dans le champ, attente de 1Password
                                   │  clic irréversible (payer, envoyer, supprimer…) → arrêt avec « confirm »
                                   ▼
appelant ◀── une ligne JSON : status, actions, url, title, text, target
```

- **Aucun LLM de texte.** Les valeurs viennent de `--values`. Un champ sans valeur correspondante renvoie `need_value`.
- **Les identifiants restent dans 1Password.** jevnav ne tape jamais un identifiant, une adresse mail, un mot de passe ou un code. Avant chaque frappe, il contrôle l'élément réel (type, autocomplétion, mode de saisie, libellés, focus), et il s'arrête sur les formulaires de connexion jusqu'à ce que vous les remplissiez et cliquiez le bouton de connexion.
- **Reprise possible.** L'onglet reste ouvert ; `--target` repart de là où l'appel précédent s'est arrêté.
- **Deux branchements.** Une commande Bash pour Claude Code, et un serveur MCP (`jev_ultrafast/mcp_server.py`) pour le chat de Claude Desktop.

Mesures du 4 octobre 2026, trois passages par tâche, chacun vérifié sur la page finale : recherche Wikipédia 3,7 s, recherche de vol aller simple sur Google Flights 9,1 s, bouton asynchrone 3,9 s, les 12 passages validés. Sur la plus simple de ces tâches, Claude seul met 27 à 42 s. Détails et limites : [benchmark](docs/fr/benchmark.md).

## Comment l'utiliser

Prérequis : macOS, Comet ou Chrome 144+, [uv](https://docs.astral.sh/uv/), une clé API TypeSafe, 1Password et son extension de navigateur.

```bash
git clone https://github.com/Matthieusabourin2/jev-ultrafast.git ~/jev-ultrafast
cd ~/jev-ultrafast && uv sync
printf 'TYPESAFE_API_KEY=votre_cle\nTYPESAFE_MODEL=jev-latest\n' > .env
```

Dans le navigateur, ouvrez `chrome://inspect/#remote-debugging`, cochez **Allow remote debugging for this browser instance**, puis cliquez **Allow** quand le premier lancement le demande. Ce clic se refait après chaque redémarrage du navigateur.

```bash
uv run --env-file .env jevnav --url https://en.wikipedia.org/wiki/Main_Page \
  --goal "Search Wikipedia for Alan Turing and open his article" --values '{"query":"Alan Turing"}' --close
```

Statuts : `done`, `need_value`, `confirm` (relancer avec `--confirm "<libellé>"` une fois l'accord de l'utilisateur obtenu), `login_timeout`, `in_progress`, `refused`, `blocked`, `error`. Le pas-à-pas complet, la règle pour Claude Code, le branchement MCP de Claude Desktop et le dépannage sont dans le [guide d'installation](docs/fr/installation.md).

Vérifications : `uv run pytest -q tests` (tests unitaires), `uv run --env-file .env python examples/guards.py` (gardes d'identifiants dans le vrai navigateur), `uv run --env-file .env python bench/run.py --runs 3` (banc de performance).

---

<details>
<summary><strong>README d'origine (anglais)</strong>, reproduit sans modification</summary>

<img src="docs/banner.svg" alt="Jev Ultrafast · Browser Use × TypeSafe" width="100%" />

# Jev Ultrafast ⚡

> [!IMPORTANT]
> **The Browser Use Cloud waitlist is open.** Get early access to ultrafast browser agents in the cloud.
> **[Join the waitlist →](https://browser-use.com/ultrafast?utm_source=github&utm_medium=readme&utm_campaign=jev-ultrafast)**

**A browser agent with a dynamic, indexed action space.**

Give it one goal. [TypeSafe's Jev](https://docs.typesafe.ai/introduction) picks an operation and an element. A small LLM writes text only when the operation is `TYPE_TEXT`.

**Zürich → London on Google Flights in 7.1 seconds.** One natural-language goal, actual text generation, and loading waits included.

<a href="docs/demo.mp4"><img src="docs/demo.gif" alt="A real Google Flights search at 1× speed, with generated city names and dynamic operation/target decisions" width="100%" /></a>

[Watch the MP4](docs/demo.mp4) · [Measurements](docs/performance.md) · [Read the loop](jev_ultrafast/agent.py)

## The action space

Every observation produces a new element table:

```text
[1] button    Change ticket type · Round trip
[2] combobox  Where from?        · San Francisco
[3] combobox  Where to?          · empty
[4] textbox   Departure          · empty
...
```

The operations are `CLICK`, `TYPE_TEXT`, `SELECT`, `SCROLL_UP`, `SCROLL_DOWN`, `WAIT`, `DONE`, and `BLOCKED`. Only supported operations and targets are offered.

```text
                      one TypeSafe request
                     ┌───────────────────────────┐
page → element table → operation                 │
                     │ click_target              │
                     │ type_text_target          │
                     │ select_target, if present │
                     └─────────────┬─────────────┘
                         use the matching target
                                   │
                    CLICK [7] ─────┤──→ browser
                TYPE_TEXT [3] ─────┘
                          ↓
                   small LLM → text → browser
```

Target questions are speculative. If the operation is `CLICK`, only `click_target` can execute. Two decisions, **one network round trip**. Each target head contains only compatible elements. Native dropdown choices carry an observed element/option index.

There are no site-specific action scripts or prepared field strings in the policy. The Flights example supplies a goal and independently verifies the outcome. The screenshot renderer adds labels afterward; it does not drive the browser.

## Try it

```bash
git clone https://github.com/browser-use/jev-ultrafast.git
cd jev-ultrafast
uv sync
cp .env.example .env
# Add TYPESAFE_API_KEY and TEXT_MODEL_API_KEY.
uv run jev
```

Open **http://127.0.0.1:8766** and click **Start demo → Run automatically**. The inspector shows numbered elements, operation probabilities, target probabilities, and executed actions. **Choose next** pauses before execution.

Chrome connects through [Browser Harness](https://github.com/browser-use/browser-harness), installed by `uv sync`. Run `uv run browser-harness --doctor` if it needs connecting. Allow remote debugging in Chrome when prompted.

`TEXT_MODEL_API_KEY` is an OpenRouter key in the example configuration. The current demo uses `inception/mercury-2.5` with reasoning disabled. Gemini, GLM, and DeepSeek can also use the OpenAI-compatible text helper; configure the appropriate model, endpoint, and reasoning setting.

## Use the library

```python
from jev_ultrafast import Agent

with Agent(
    "https://www.google.com/travel/flights?hl=en",
    "Find one-way flights from Zurich to London on September 20, 2026, "
    "for one adult in economy. Stop when matching flight options are visible.",
) as agent:
    for state in agent.run():
        print(state["elapsed_ms"], state["status"])
```

Run with `uv run --env-file .env python your_script.py`. The same policy can run a different task:

```bash
uv run --env-file .env python examples/run.py \
  --url https://en.wikipedia.org/wiki/Main_Page \
  --goal 'Find and open the Wikipedia article about Gödel’s incompleteness theorems.'
```

`uv run --env-file .env python examples/flights.py --keep-open` performs the flight search, checks the actual route/date/results, and saves its trace. It does not select or book a flight.

## Why it moves

- **One request per decision cycle.** Operation and target heads share the same observed state.
- **No screenshots in the default agent loop.** Jev consumes structured state. The inspector opts into screenshots; the video uses a separate continuous screencast.
- **One browser call per snapshot.** Read visible controls, their names, values, and text atomically. Keep references to the actual DOM nodes.
- **Validate the selected target.** Clicks check the document, form values, target, and nearby context. Animation alone does not force another prediction. Resolve current geometry and reject covered controls before input.
- **Wait for useful state.** After typing into a combobox, wait for visible suggestions, capped at 200 ms. Other interactions get at most two animation frames or 50 ms. These reads happen after execution is logged.
- **Keep hidden tabs rendering.** Focus emulation prevents background animation throttling without switching Chrome's visible tab.
- **Send visible text.** Offscreen article bodies and footers do not fill the model context.
- **Reuse an interrupted text request.** A generated value survives a stale-page retry only if the entire text-helper input is unchanged.

Every executed target is resolved from an observed node. The executor rechecks page freshness and click occlusion. Model output never becomes selectors, coordinates, shell commands, or executable JavaScript. Text-helper output must parse as a small JSON object before typing.

## Small enough to read

| File | Job |
| --- | --- |
| [agent.py](jev_ultrafast/agent.py) | The complete loop and text-helper handoff |
| [snapshot.js](jev_ultrafast/snapshot.js) | Atomic DOM snapshot, indexed controls, freshness guards |
| [browser.py](jev_ultrafast/browser.py) | Browser connection, current geometry, execution |
| [model.py](jev_ultrafast/model.py) | Dynamic operation/target heads and text generation |
| [questions.py](jev_ultrafast/questions.py) | Model instructions |
| [demo.py](jev_ultrafast/demo.py) | Local inspector |

## Evidence and limits

The current video is a **7,073 ms** Google Flights run. Timing starts after initial page observation and includes model calls, generated text, browser work, stale decisions, and loading waits. A fresh independent check verifies the one-way setting, Zürich, London, September 20, 2026, and visible flight options. The video plays at 1×, with no opening hold and a 0.5-second final hold.

In six alternating runs with identical models and settings, both versions passed **3/3**. Median task time went from **9.450 s → 7.092 s**, a **25% reduction**; median browser protocol calls went from **1,092 → 101**. This is three repeats of one task on one browser profile, not a general reliability benchmark.

The same policy opened the requested Wikipedia article in **2.798 s** and passed a local hotel search/filter task in **1.896 s**. Runs, failures, source hashes, and measurement boundaries are in [performance.md](docs/performance.md).

A `DONE` choice still requires independent outcome verification. The DOM reader handles common HTML and ARIA controls, not the full accessible-name specification. Shadow roots, frames, canvas, uploads, pop-up tabs, nested scrolling, and arbitrary keyboard widgets remain outside this MVP. Owned tabs share the existing Chrome profile.

## Development

```bash
uv run ruff check .
uv run pytest
node --check jev_ultrafast/static/app.js
node --check jev_ultrafast/snapshot.js
uv build
```

Tests are offline. `uv run python scripts/check_guards.py` checks real controls in a local browser without model calls. Live examples and recording scripts make paid API calls. `scripts/record_flights.py <new-folder>` captures original browser timestamps; `scripts/render_demo.py <recording-folder>` renders that verified run at 1× and crops out the Google account strip. Credentials and raw traces stay ignored.

---

[Browser Use](https://github.com/browser-use/browser-use) · [Browser Harness](https://github.com/browser-use/browser-harness) · [TypeSafe speculative fan-out](https://docs.typesafe.ai/patterns/fan-out)

</details>
