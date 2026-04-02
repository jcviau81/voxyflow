# VoxyFlow — Plan de correction

> Audit du 1er avril 2026. Classement par priorite et severite.
> Chaque etape est independante sauf indication contraire.

---

## Phase 1 — Securite (CRITIQUE)

Ces correctifs doivent etre faits **avant tout deploiement** au-dela de localhost.

### 1.1 Retirer les cles API du code source

**Severite**: CRITIQUE
**Fichiers concernes**:
- `settings.json` (ligne ~16-32) — contient `sk-cliproxy-thething-001`
- `settings.json.example` — ne doit contenir que des placeholders

**Actions**:
1. Ajouter `settings.json` au `.gitignore`
2. Creer un `settings.json.example` avec des valeurs placeholder (`"YOUR_API_KEY_HERE"`)
3. Supprimer `settings.json` du suivi git: `git rm --cached settings.json`
4. Documenter dans le README comment configurer les cles (env vars ou fichier local)
5. Scanner l'historique git pour les cles exposees (utiliser `git filter-repo` ou `BFG Repo-Cleaner` si le repo est public)

**Validation**: `grep -r "sk-" . --include="*.json" --include="*.py"` ne retourne rien de committe.

---

### 1.2 Restreindre la configuration CORS

**Severite**: CRITIQUE
**Fichier**: `backend/app/main.py` (lignes ~174-180)

**Avant**:
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**Apres**:
```python
_ALLOWED_ORIGINS = os.environ.get(
    "VOXYFLOW_CORS_ORIGINS",
    "http://localhost:5173,http://localhost:3000"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
```

**Validation**: Tester un `fetch()` depuis une origine non listee — doit etre refuse.

---

### 1.3 Remplacer `create_subprocess_shell` par `create_subprocess_exec`

**Severite**: HAUTE
**Fichier**: `backend/app/services/tools/system_tools.py` (ligne ~154)

**Avant**:
```python
proc = await asyncio.create_subprocess_shell(command, ...)
```

**Apres**:
```python
import shlex
args = shlex.split(command)
proc = await asyncio.create_subprocess_exec(*args, ...)
```

**Validation**: Tester avec une commande contenant `; rm -rf /` — doit echouer proprement.

---

### 1.4 Preparer un stub d'authentification

**Severite**: HAUTE
**Fichier**: `frontend-react/src/hooks/useAuth.ts`

**Actions**:
1. Pour l'instant (usage local), garder `isAuthenticated = true` mais mettre a jour le commentaire:
   ```typescript
   // WARNING: Auth bypassed for local development only.
   // Must implement real auth before any network deployment.
   const isAuthenticated = true;
   ```
2. Creer un ticket/TODO pour implementer un vrai auth flow (API key header ou OAuth) avant deploiement
3. Ajouter un middleware FastAPI cote backend qui valide un header `X-API-Key` (meme un simple token local)

---

## Phase 2 — Splitter les fichiers monstres

Objectif: aucun fichier ne devrait depasser ~500 lignes.

### 2.1 Decouper `claude_service.py` (2,767 lignes)

**Fichier**: `backend/app/services/claude_service.py`

**Decoupage propose**:

| Nouveau fichier | Responsabilite | Lignes approximatives a extraire |
|---|---|---|
| `services/llm/client_factory.py` | Creation des clients Anthropic/OpenAI | `_make_anthropic_client`, `_make_async_anthropic_client`, `_make_openai_client` |
| `services/llm/model_router.py` | Selection du modele selon le layer (fast/deep/analyzer) | Logique de routing des modeles |
| `services/llm/message_handler.py` | Construction et envoi des messages | Preparation des prompts, streaming |
| `services/llm/tool_executor.py` | Execution des tools et parsing des resultats | Tool calls, delegation |
| `services/llm/cache_manager.py` | Gestion du cache et de l'historique | Cache prompt, history management |

**Etapes**:
1. Creer le dossier `backend/app/services/llm/`
2. Extraire chaque module un a la fois, en gardant les imports fonctionnels
3. `claude_service.py` devient un facade mince qui delegue aux sous-modules
4. Tester apres chaque extraction (pas tout d'un coup)

---

### 2.2 Decouper `chat_orchestration.py` (2,656 lignes)

**Fichier**: `backend/app/services/chat_orchestration.py`

**Decoupage propose**:

| Nouveau fichier | Responsabilite |
|---|---|
| `services/orchestration/fast_layer.py` | Logique du mode Fast |
| `services/orchestration/deep_layer.py` | Logique du mode Deep |
| `services/orchestration/analyzer_layer.py` | Logique de l'Analyzer |
| `services/orchestration/delegate_handler.py` | Parsing et execution des blocs delegate |
| `services/orchestration/event_bus.py` | Systeme d'evenements interne |

**Meme approche**: extraction incrementale, test apres chaque etape.

---

### 2.3 Decouper `KanbanBoard.tsx` (1,049 lignes)

**Fichier**: `frontend-react/src/components/Kanban/KanbanBoard.tsx`

**Decoupage propose**:

| Nouveau fichier | Responsabilite |
|---|---|
| `Kanban/KanbanColumn.tsx` | Rendu d'une colonne individuelle |
| `Kanban/KanbanCardWrapper.tsx` | Wrapper de carte avec drag-drop |
| `Kanban/hooks/useDragDrop.ts` | Logique de drag-and-drop extraite |
| `Kanban/hooks/useKanbanFilters.ts` | Logique de filtrage |
| `Kanban/KanbanBoard.tsx` | Conteneur principal (devrait tomber a ~200 lignes) |

---

### 2.4 Decouper `ChatProvider.tsx` (946 lignes)

**Fichier**: `frontend-react/src/contexts/ChatProvider.tsx`

**Actions**:
1. Extraire les hooks custom dans des fichiers separes (`useChatSession.ts`, `useChatMessages.ts`)
2. Extraire la logique WebSocket dans un hook dedie (`useWebSocket.ts`) si pas deja fait
3. Le provider ne devrait contenir que le wiring entre les hooks

---

## Phase 3 — Error handling

### 3.1 Remplacer les `except Exception: pass` par du logging

**Fichiers concernes** (liste non exhaustive):
- `backend/app/config.py` (ligne ~37)
- `backend/app/services/personality_service.py` (ligne ~455)
- `backend/app/services/scheduler_service.py` (ligne ~350)

**Pattern a appliquer**:

```python
# AVANT
try:
    do_something()
except Exception:
    pass

# APRES
try:
    do_something()
except Exception:
    logger.exception("Failed to do_something")
    # Re-raise si c'est un path critique, ou continuer si c'est optionnel
```

**Actions**:
1. `grep -rn "except Exception" backend/` pour lister tous les cas
2. Pour chaque occurrence, decider: est-ce un path critique (re-raise) ou optionnel (log + continuer)?
3. Ajouter `logger.exception()` partout — jamais de `pass` silencieux

---

### 3.2 Proteger le path WebSocket critique

**Fichier**: `backend/app/main.py` (ligne ~341)

**Avant**:
```python
new_tasks = await _orchestrator.handle_message(...)
if new_tasks:
    bg_tasks.extend(new_tasks)
```

**Apres**:
```python
try:
    new_tasks = await _orchestrator.handle_message(...)
    if new_tasks:
        bg_tasks.extend(new_tasks)
except Exception:
    logger.exception("Orchestration failed for message")
    await websocket.send_json({
        "type": "error",
        "message": "Internal error processing your message. Please retry."
    })
```

---

### 3.3 Ajouter un Error Boundary React

**Fichier a creer**: `frontend-react/src/components/ErrorBoundary.tsx`

```tsx
import { Component, type ReactNode } from "react";

interface Props { children: ReactNode; fallback?: ReactNode; }
interface State { hasError: boolean; }

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };
  static getDerivedStateFromError() { return { hasError: true }; }
  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error("ErrorBoundary caught:", error, info);
  }
  render() {
    if (this.state.hasError) {
      return this.props.fallback ?? <div>Something went wrong. Please refresh.</div>;
    }
    return this.props.children;
  }
}
```

Wrapper le composant racine dans `App.tsx` avec `<ErrorBoundary>`.

---

## Phase 4 — Configuration et constantes

### 4.1 Unifier les sources de configuration

**Probleme**: 5 sources (env vars, `.env`, `settings.json`, DB, hardcode).

**Solution**: Etablir une hierarchie claire et documentee:

```
Priorite (la plus haute gagne):
1. Variables d'environnement (override runtime)
2. Base de donnees app_settings (config utilisateur persistee)
3. settings.json (config fichier local)
4. Valeurs par defaut dans config.py (fallback)
```

**Actions**:
1. Documenter cette hierarchie dans `backend/app/config.py` en commentaire de tete
2. Creer une fonction `get_setting(key)` centralisee qui respecte cette priorite
3. Supprimer les lectures ad-hoc de settings.json eparpillees dans le code

---

### 4.2 Extraire les magic strings en enums

**Fichiers concernes**: `database.py`, `KanbanBoard.tsx`, routes diverses

**Actions**:

Backend — creer `backend/app/models/enums.py`:
```python
from enum import StrEnum

class CardStatus(StrEnum):
    IDEA = "idea"
    TODO = "todo"
    IN_PROGRESS = "in-progress"
    DONE = "done"
    CARD = "card"

class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
```

Frontend — creer `frontend-react/src/constants/statuses.ts`:
```typescript
export const CARD_STATUS = {
  IDEA: "idea",
  TODO: "todo",
  IN_PROGRESS: "in-progress",
  DONE: "done",
} as const;
```

Remplacer toutes les strings hardcodees par les enums/constantes.

---

### 4.3 Eliminer les localhost hardcodes

**Fichiers concernes**:
- `backend/app/config.py` (ligne ~73)
- `backend/app/services/scheduler_service.py` (lignes ~163-164)
- `backend/app/routes/models.py` (ligne ~117)
- `backend/app/routes/settings.py` (lignes ~79, 85, 91)

**Action**: Remplacer chaque occurrence par une lecture de `config.py` ou d'une variable d'environnement:
```python
# config.py
api_base_url: str = os.environ.get("VOXYFLOW_API_BASE", "http://localhost:3457/v1")
```

Puis utiliser `settings.api_base_url` partout au lieu de la string hardcodee.

---

## Phase 5 — Performance et qualite frontend

### 5.1 Ajouter le virtual scrolling pour les messages

**Fichier**: `frontend-react/src/components/Chat/MessageList.tsx`

**Actions**:
1. `@tanstack/react-virtual` est deja installe — l'utiliser
2. Implementer un `useVirtualizer` pour la liste de messages
3. Tester avec 1000+ messages pour valider la fluidite

---

### 5.2 Optimiser le card store avec Immer

**Fichier**: `frontend-react/src/stores/useCardStore.ts`

**Avant**:
```typescript
set((state) => ({
  cardsById: { ...state.cardsById, [card.id]: card },
}));
```

**Apres**:
```typescript
// Dans la creation du store, ajouter le middleware Immer
import { immer } from "zustand/middleware/immer";

// Puis:
set((state) => {
  state.cardsById[card.id] = card;
});
```

---

### 5.3 Ajouter la pagination cote API

**Fichiers**: routes backend qui retournent des listes (cards, messages, projects)

**Actions**:
1. Ajouter des parametres `?page=1&per_page=50` aux endpoints de liste
2. Retourner un objet `{ items: [], total: N, page: N, per_page: N }`
3. Adapter le frontend pour charger par page ou en infinite scroll

---

## Phase 6 — Architecture et patterns

### 6.1 Remplacer les singletons par de l'injection de dependances

**Fichiers concernes**: tous les `get_*_service()` dans `backend/app/`

**Actions**:
1. Utiliser le systeme de `Depends()` de FastAPI:
```python
async def get_rag(rag: RAGService = Depends(get_rag_service)):
    ...
```
2. Cela rend les services mockables pour les tests
3. Migration incrementale: un service a la fois

---

### 6.2 Consolider la factory de clients API

**Fichier**: `backend/app/services/claude_service.py`

**Avant**: 3 fonctions quasi-identiques (`_make_anthropic_client`, `_make_async_anthropic_client`, `_make_openai_client`)

**Apres**: une seule factory:
```python
def make_llm_client(provider: str, *, async_mode: bool = True) -> Any:
    if provider == "anthropic":
        cls = AsyncAnthropic if async_mode else Anthropic
        return cls(api_key=..., base_url=...)
    elif provider == "openai":
        return AsyncOpenAI(api_key=..., base_url=...)
    raise ValueError(f"Unknown provider: {provider}")
```

---

### 6.3 Migrer vers Alembic pour les migrations DB

**Fichier actuel**: `backend/app/database.py` (lignes ~47-157) — raw SQL a chaque startup

**Actions**:
1. `pip install alembic` + `alembic init migrations`
2. Generer une migration initiale a partir du schema SQLAlchemy actuel
3. Convertir les migrations manuelles existantes en scripts Alembic
4. Supprimer le code de migration ad-hoc de `init_db()`
5. Documenter: `alembic upgrade head` dans le README

---

## Phase 7 — Nettoyage et hygiene

### 7.1 Supprimer le code commente

**Fichiers concernes**: `requirements.txt` (lignes ~20-24), et tout autre fichier avec du code commente

**Regle**: si c'est commente depuis plus de 2 semaines et jamais utilise, supprimer. Git garde l'historique.

---

### 7.2 Mettre a jour les commentaires menteurs

**Fichiers concernes**:
- `backend/app/main.py` ligne ~173: changer "single-user, localhost" pour reflete la realite
- `frontend-react/src/hooks/useAuth.ts`: avertir clairement que l'auth est bypassee
- Tout commentaire qui dit "TODO" ou "temporary" depuis plus de 3 mois: le faire ou le supprimer

---

### 7.3 Uniformiser les messages d'erreur API

**Regle a appliquer**:
- Toujours utiliser `{"detail": "Message"}` comme format d'erreur
- Toujours terminer par un point
- Utiliser des termes coherents: "Project" (pas "Repository"), "Chat" (pas "Conversation")

---

### 7.4 Retirer les imports avec underscore inutiles

**Fichier**: `backend/app/main.py` (lignes ~39-40)

```python
# AVANT
import os as _os
from logging.handlers import RotatingFileHandler as _RotatingFileHandler

# APRES
import os
from logging.handlers import RotatingFileHandler
```

---

## Ordre d'execution recommande

```
Semaine 1:  Phase 1 (securite)          — NON NEGOCIABLE
Semaine 2:  Phase 3 (error handling)     — Stabilite
Semaine 3:  Phase 4 (config/constantes)  — Maintenabilite
Semaine 4-5: Phase 2 (split fichiers)   — Lisibilite
Semaine 6:  Phase 5 (performance)        — UX
Semaine 7:  Phase 6 (architecture)       — Scalabilite
Continu:    Phase 7 (nettoyage)          — Au fur et a mesure
```

---

## Suivi

| Phase | Status | Date completee |
|---|---|---|
| 1 — Securite | TODO | |
| 2 — Split fichiers | TODO | |
| 3 — Error handling | TODO | |
| 4 — Config/constantes | TODO | |
| 5 — Performance frontend | TODO | |
| 6 — Architecture | TODO | |
| 7 — Nettoyage | TODO | |
