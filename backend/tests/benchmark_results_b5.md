# B5 Benchmark: Regex vs LLM Memory Extraction

**Date**: 2026-03-24 15:20
**Conversations tested**: 13 (10 crafted, 3 real)

## Overall Summary (Crafted Conversations)

| Metric | Regex | LLM | Winner |
|--------|-------|-----|--------|
| **Precision** | 67% | 92% | LLM |
| **Recall** | 40% | 87% | LLM |
| **Noise** | 33% | 8% | LLM |
| **Total time** | 6ms | 100631ms | Regex |

## Per-Conversation Breakdown

| # | Conversation | Lang | Expected | Regex (P/R/N) | LLM (P/R/N) | Regex count | LLM count |
|---|-------------|------|----------|---------------|-------------|-------------|-----------|
| 1 | EN: Clear technical decision | en | 2 | 100%/50%/0% | 100%/50%/0% | 1 | 1 |
| 2 | FR: Préférence de style de code | fr | 2 | 100%/50%/0% | 100%/100%/0% | 1 | 2 |
| 3 | EN: Bug report and fix | en | 2 | 67%/100%/33% | 100%/50%/0% | 3 | 1 |
| 4 | FR: Décision d'architecture | fr | 2 | 0%/0%/100% | 50%/100%/50% | 1 | 4 |
| 5 | EN: Casual chat with no memory valu | en | N/A | 0%/100%/100% | 100%/100%/0% | 1 | 0 |
| 6 | Franglais: Mixed tech discussion | mixed | 3 | 100%/0%/0% | 100%/67%/0% | 0 | 2 |
| 7 | EN: Subtle preference (no trigger w | en | 2 | 100%/0%/0% | 100%/100%/0% | 0 | 2 |
| 8 | FR: Lesson learned from incident | fr | 2 | 100%/0%/0% | 67%/100%/33% | 0 | 3 |
| 9 | EN: Version pinning decision | en | 2 | 0%/0%/100% | 100%/100%/0% | 1 | 2 |
| 10 | EN: Assistant-heavy response (noise | en | N/A | 100%/100%/0% | 100%/100%/0% | 0 | 0 |
| 11 | Real: 073bfdf8-b5c4-49ae-9d50-4c5f7 | unknown | N/A | — | — | 8 | 0 |
| 12 | Real: 170f39d7-41a6-4879-afa7-252ef | unknown | N/A | — | — | 2 | 3 |
| 13 | Real: 1dbb2aa9-a82d-492c-8404-aa441 | unknown | N/A | — | — | 8 | 1 |

## Detailed Results

### 1. EN: Clear technical decision

**Regex extracted:**
- [decision] We decided to go with Redis for caching.

**LLM extracted:**
- [decision] Redis chosen for caching layer — supports pub/sub needed for real-time notifications (conf=0.95)

**LLM missed:** ['redis', 'pub/sub', 'notification']
**Regex missed:** ['redis', 'pub/sub', 'notification']

### 2. FR: Préférence de style de code

**Regex extracted:**
- [fact] Aussi, ne jamais utiliser print() pour le debug — toujours logger.debug().

**LLM extracted:**
- [preference] Toujours utiliser async/await plutôt que des callbacks — plus lisible selon l'utilisateur. (conf=0.95)
- [preference] Ne jamais utiliser print() pour le debug — toujours utiliser logger.debug(). (conf=0.97)

**Regex missed:** ['async', 'await']

### 3. EN: Bug report and fix

**Regex extracted:**
- [fact] There's a critical bug: the WebSocket connection drops after exactly 30 seconds of inactivity.
- [fact] I fixed it by setting proxy_read_timeout 300s in the nginx config.
- [fact] Perfect, that fixed it.

**LLM extracted:**
- [lesson] WebSocket connections drop after 30 seconds of inactivity due to nginx proxy_read_timeout default (3 (conf=0.95)

**LLM missed:** ['nginx', 'proxy_read_timeout']
**Regex noise:** Perfect, that fixed it.

### 4. FR: Décision d'architecture

**Regex extracted:**
- [lesson] C'est important de toujours versionner le schéma.

**LLM extracted:**
- [decision] La base de données du projet est PostgreSQL avec SQLAlchemy comme ORM (conf=0.95)
- [decision] Le driver async utilisé pour PostgreSQL est asyncpg (conf=0.85)
- [decision] Alembic est utilisé pour les migrations de schéma de base de données (conf=0.95)
- [preference] Toujours versionner le schéma de la base de données via les migrations Alembic (conf=0.9)

**Regex missed:** ['postgresql', 'sqlalchemy'], ['alembic', 'migration']
**LLM noise:** Le driver async utilisé pour PostgreSQL est asyncpg; Toujours versionner le schéma de la base de données via les migrations Alembic
**Regex noise:** C'est important de toujours versionner le schéma.

### 5. EN: Casual chat with no memory value

**Regex extracted:**
- [fact] No problem, I'm here whenever you're ready.

**LLM extracted:**
- _(nothing)_

**Regex noise:** No problem, I'm here whenever you're ready.

### 6. Franglais: Mixed tech discussion

**Regex extracted:**
- _(nothing)_

**LLM extracted:**
- [fact] Le frontend Voxyflow est en React avec TypeScript (migration depuis JavaScript complétée) (conf=0.95)
- [lesson] Les tests unitaires Jest ne suffisent pas — des tests e2e avec Playwright sont aussi nécessaires (conf=0.85)

**LLM missed:** ['javascript', 'typescript', 'switch']
**Regex missed:** ['react', 'typescript'], ['javascript', 'typescript', 'switch'], ['jest', 'playwright', 'e2e']

### 7. EN: Subtle preference (no trigger words)

**Regex extracted:**
- _(nothing)_

**LLM extracted:**
- [preference] Keep functions under 30 lines. Small functions are easier to test. (conf=0.95)
- [preference] Every public function needs a docstring, no exceptions. (conf=0.95)

**Regex missed:** ['function', '30 lines'], ['docstring', 'public function']

### 8. FR: Lesson learned from incident

**Regex extracted:**
- _(nothing)_

**LLM extracted:**
- [fact] Incident en prod: le service de mémoire a crashé parce que ChromaDB n'avait plus d'espace disque (conf=0.95)
- [lesson] Toujours ajouter un health check qui vérifie l'espace disque disponible avant d'écrire dans ChromaDB (conf=0.95)
- [decision] Il faut monitorer l'espace disque de ChromaDB en production (conf=0.8)

**Regex missed:** ['chromadb', 'espace disque', 'crash'], ['health check', 'espace disque']
**LLM noise:** Il faut monitorer l'espace disque de ChromaDB en production

### 9. EN: Version pinning decision

**Regex extracted:**
- [preference] Don't use any 3.13 features.

**LLM extracted:**
- [decision] Python is pinned to 3.12 for the Voxyflow project — do not use any 3.13 features (conf=0.95)
- [decision] Project uses uv instead of pip for package management (chosen for speed) (conf=0.95)

**Regex missed:** ['python', '3.12'], ['uv', 'pip', 'package']
**Regex noise:** Don't use any 3.13 features.

### 10. EN: Assistant-heavy response (noise test)

**Regex extracted:**
- _(nothing)_

**LLM extracted:**
- _(nothing)_


### 11. Real: 073bfdf8-b5c4-49ae-9d50-4c5f76

**Regex extracted:**
- [fact] Move "Add error handling & polish" to in-progress.
- [fact] Moving "Build weather display" to done and pulling "Add error handling & polish" into in-progress.
- [fact] <delegate>
{"intent": "move_card", "summary": "Move 'Build weather display' to done, and move 'Add e
- [fact] Error handling and polish is done!
- [fact] All done — moving "Add error handling & polish" to done.
- [fact] 🎯

<delegate>
{"intent": "move_card", "summary": "Move 'Add error handling & polish' to done in Weat
- [fact] Based on the conversation, here's where Weather Dashboard stands:

**All 5 cards completed:** ✅

| #
- [fact] 0 remaining.**

The full dependency chain played out cleanly — scaffolding first, then UI and API in

**LLM extracted:**
- _(nothing)_

### 12. Real: 170f39d7-41a6-4879-afa7-252ef0

**Regex extracted:**
- [fact] The problem: on mobile, pressing the browser back button exits the app instead of performing in-app 
- [fact] Read the frontend code structure first — check frontend/src/components/ for modals and navigation pa

**LLM extracted:**
- [decision] Voxyflow mobile: implémentation d'un bouton back contextuel via l'API History (pushState/popstate) p (conf=0.9)
- [fact] Card 'Mobile card modal — 3-tab layout' (170f39d7) déplacée en status 'done' (conf=0.85)
- [fact] Redesign de l'onglet Details (Tab 3 / rightCol) du modal carte mobile est en cours — sections metada (conf=0.8)

### 13. Real: 1dbb2aa9-a82d-492c-8404-aa4416

**Regex extracted:**
- [fact] Move "Add error handling & polish" to in-progress.
- [fact] **Error Handling & Edge Cases** (todo)
5.
- [fact] **Responsive Styling & Polish** (todo)

Based on everything you've described across this conversatio
- [fact] <delegate>
{"intent": "move_cards_batch", "summary": "Pending user confirmation — move API Integrati
- [fact] Error handling and polish is done!
- [fact] Moving Error Handling & Edge Cases to done.
- [fact] <delegate>
{"intent": "move_card", "summary": "Move 'Error Handling & Edge Cases' to done status", "
- [fact] Based on the project state:

**Weather Dashboard — Status Summary**

| Status | Count |
|--------|--

**LLM extracted:**
- [fact] Weather Dashboard project has 10 total tasks including: API Integration Setup, City Search UI, Weath (conf=0.75)

## Verdict

| | Regex | LLM |
|---|-------|-----|
| F1 Score | 50% | 89% |
| Avg Precision | 67% | 92% |
| Avg Recall | 40% | 87% |
| Avg Noise | 33% | 8% |
| Total Latency | 6ms | 100631ms |

**LLM extraction wins** with F1 89% vs 50% (Δ=+39%).

**Key observations:**
- LLM has better recall (87% vs 40%) — catches more of the expected memories
- LLM has better precision (92% vs 67%) — less irrelevant output
- LLM produces less noise (8% vs 33%)
- LLM is ~15687x slower (expected — API calls vs local regex)
- B4 cost optimization (throttle + regex pre-filter) mitigates LLM latency in production
