# Voxyflow — Context & Workflow Guide

> Comment Voxyflow sait toujours _de quoi_ tu parles, et comment en tirer parti.

---

## Le concept de contexte

Quand tu parles à Voxy, elle n'est jamais dans le vide. Elle sait toujours où tu te trouves dans l'interface — et elle adapte ce qu'elle peut faire, ce qu'elle voit, et comment elle répond.

Il y a trois niveaux de contexte. Le niveau actif se détermine automatiquement selon ce que tu as ouvert dans l'interface :

```
Tu es sur le Main Board (onglet principal)
→ CONTEXTE GÉNÉRAL — Voxy voit tous tes projets, le Main Board, rien de spécifique.

Tu as ouvert un projet
→ CONTEXTE PROJET — Voxy voit toutes les cartes du projet, le wiki, l'historique.

Tu as ouvert une carte
→ CONTEXTE CARTE — Voxy est focalisée sur cette tâche précise, son contenu, son agent.
```

**Tu ne configures rien.** Tu navigues dans l'interface, et le contexte suit.

---

## Ce que le contexte change concrètement

### Contexte général — vue d'ensemble

Quand aucun projet n'est sélectionné (tu es sur le Main Board) :

- Voxy peut créer des projets, lister tes projets existants, gérer le Main Board
- Elle peut faire des recherches web, exécuter des commandes système
- Elle planifie des tâches (jobs cron, rappels)
- Elle ne "voit" pas l'intérieur d'un projet spécifique — si tu lui demandes des infos sur un projet, elle doit d'abord l'ouvrir

**Bon pour :** Démarrer un nouveau projet, avoir une vue d'ensemble, les tâches qui ne sont pas liées à un projet précis.

### Contexte projet — travail sur un projet

Quand tu es dans l'onglet d'un projet :

- Voxy voit toutes les cartes du projet (titre, statut, priorité, agent assigné)
- Elle a accès au wiki du projet et aux documents indexés dans RAG
- Elle peut créer, modifier, déplacer des cartes directement
- Elle peut générer un standup, un brief, ou une analyse de santé du projet
- La description et le contexte du projet sont injectés dans son prompt système

**Bon pour :** Gérer les tâches du projet, brainstormer, créer des cartes, avoir un rapport de statut.

### Contexte carte — exécution d'une tâche

Quand tu ouvres une carte spécifique :

- Voxy voit le titre, la description, le statut, la priorité, la checklist, les commentaires
- Elle adapte sa personnalité selon l'agent assigné à la carte (Coder, Researcher, Writer, etc.)
- Elle peut modifier la checklist, logger du temps, ajouter des commentaires
- Elle a accès à tous les outils — c'est le niveau le plus puissant

**Bon pour :** Travailler sur une tâche précise, demander de l'aide pour l'implémenter, enrichir les détails, faire du pair programming.

---

## La mémoire est isolée par contexte

Chaque contexte a sa propre histoire de conversation :

- La conversation dans le **projet A** n'est pas visible dans le **projet B**
- La conversation sur la **carte "Refactor auth"** n'est pas mélangée avec celle du projet
- Le **Main Board** a sa propre conversation séparée de tout projet

Tu peux avoir 5 sessions parallèles par contexte (onglets dans le panneau chat). Les historiques persistent entre les sessions — tu peux fermer l'app et retrouver ta conversation là où tu l'avais laissée.

---

## Exemple concret : créer un projet DailyOps

DailyOps est un cas d'usage typique : un projet pour gérer les tâches récurrentes du quotidien — standup, review de la semaine, inbox d'idées. Voici comment le mettre en place de A à Z.

---

### Étape 1 — Créer le projet (contexte général)

Depuis le **Main Board**, dis à Voxy :

> "Crée un projet qui s'appelle DailyOps. C'est pour gérer mes tâches quotidiennes récurrentes — standup du matin, revue hebdomadaire, capture d'idées."

Voxy va créer le projet et t'y emmener. Tu peux aussi le créer manuellement via le bouton **+** dans la sidebar.

---

### Étape 2 — Configurer le contexte du projet (contexte projet)

Une fois dans DailyOps, prends un moment pour décrire le projet à Voxy. Cette description est injectée dans son prompt système à chaque message :

> "Mets à jour la description du projet : DailyOps est mon système de routines quotidiennes. L'objectif est d'avoir des tâches récurrentes qui se régénèrent automatiquement, et un espace pour capturer les idées en vrac sans interrompre mon flux."

Tu peux aussi le faire via **l'icône d'édition du projet** dans l'interface.

---

### Étape 3 — Créer les cartes récurrentes

#### Carte 1 : Standup du matin

Depuis le contexte projet, dis :

> "Crée une carte 'Morning Standup' avec l'agent Researcher. Description : faire le point sur ce qui est prévu aujourd'hui — regarder les cartes en cours, les blocages, les priorités. Checklist : Quoi était prévu hier ? Quoi est prévu aujourd'hui ? Blocages ? Rend la carte récurrente tous les jours (weekdays)."

Ou crée la carte manuellement, puis configure la récurrence dans le détail de la carte (**champ Recurrence**).

**Récurrences disponibles :**

| Valeur | Fréquence |
|--------|-----------|
| `daily` | Chaque jour |
| `weekdays` | Lundi–Vendredi (weekends ignorés) |
| `weekly` | Chaque semaine |
| `biweekly` | Toutes les deux semaines |
| `monthly` | Chaque mois |
| `hourly` | Chaque heure |
| `6hours` | Toutes les 6 heures |

Quand la date de prochaine occurrence est atteinte, le scheduler crée automatiquement une copie fraîche de la carte (statut `idea`, titre et description préservés) et replanifie la prochaine occurrence.

#### Carte 2 : Weekly Review

> "Crée une carte 'Weekly Review' avec l'agent Architect. Description : revue complète de la semaine — cartes terminées, en attente, décisions prises. Récurrence hebdomadaire, tous les vendredis."

#### Carte 3 : Inbox

> "Crée une carte 'Inbox — idées et captures' en statut Todo, aucun agent. Description : dépôt temporaire pour toutes les idées qui arrivent pendant la semaine. À trier chaque vendredi lors de la Weekly Review."

L'inbox n'est pas récurrente — c'est une carte persistante que tu vides manuellement lors de la revue.

---

### Étape 4 — Travailler sur une carte (contexte carte)

Le lundi matin, tu ouvres la carte **Morning Standup** (générée automatiquement). Voxy est maintenant focalisée sur cette carte.

Tu peux dire :

> "Lance le standup."

Voxy va :
1. Regarder les cartes en cours dans le projet
2. Identifier les blocages potentiels
3. Te donner un résumé structuré
4. Cocher les items de la checklist au fur et à mesure

Ou plus simplement :

> "Qu'est-ce que j'avais prévu hier ?"

Elle va consulter l'historique de la conversation sur cette carte (sessions précédentes) et les commentaires enregistrés.

---

### Étape 5 — Automatiser avec un Board Run (optionnel)

Un **Board Run** est un job planifié qui exécute automatiquement toutes les cartes d'un projet dans un statut donné — sans intervention manuelle.

Pour DailyOps, tu peux configurer un Board Run qui lance automatiquement les cartes `todo` chaque matin :

Depuis le contexte général ou projet, dis :

> "Crée un job Board Run pour le projet DailyOps, chaque jour à 8h, qui exécute les cartes en statut 'todo'."

Ou via l'API :

```bash
curl -X POST http://localhost:8000/api/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "name": "DailyOps — Morning Run",
    "type": "board_run",
    "cron": "0 8 * * 1-5",
    "enabled": true,
    "payload": {
      "project_id": "TON_PROJECT_ID",
      "statuses": ["todo"]
    }
  }'
```

Le Board Run va spawner des workers pour chaque carte éligible, les exécuter en parallèle, et envoyer les résultats via WebSocket.

---

### Étape 6 — Utiliser le wiki du projet

Depuis le contexte projet, le wiki de DailyOps peut servir de référence permanente — checklist de review, templates de standup, notes de contexte.

> "Crée une page wiki 'Templates' avec un template de standup et un template de weekly review."

Voxy va créer la page. Elle est ensuite disponible comme contexte pour les workers.

---

## Patterns de workflow utiles

### Capturer une idée sans perdre le fil

Tu es en train de travailler sur une carte (contexte carte). Une idée arrive.

**Ne change pas de contexte.** Dis simplement :

> "Note quelque chose pour moi en dehors de cette carte : explorer la migration vers PostgreSQL pour les performances."

Voxy va créer une carte dans l'inbox du projet (ou sur le Main Board si précisé) sans te sortir de ton contexte actuel.

---

### Déléguer sans attendre

Le Dispatcher (Voxy en mode conversation) ne bloque jamais. Si tu demandes quelque chose qui prend du temps :

> "Fais une analyse de toutes les cartes en cours et dis-moi lesquelles sont les plus à risque."

Voxy va répondre immédiatement ("Je lance l'analyse...") et envoyer un **worker** en arrière-plan. Tu peux continuer à parler pendant qu'il travaille. Le résultat arrive dans le chat quand le worker a fini.

---

### Enrichir une carte rapidement

Ouvre une carte avec juste un titre. Dis :

> "Enrichis cette carte."

Voxy va générer une description détaillée, des critères d'acceptation, et des suggestions de checklist basés sur le titre et le contexte du projet.

---

### Standup rapide en contexte projet

Sans ouvrir de carte, depuis le contexte projet :

> "Donne-moi le standup du projet."

Voxy appelle `voxyflow.ai.standup` et génère un résumé structuré : ce qui est terminé, en cours, bloqué.

---

### Changer de session

Chaque contexte (projet ou carte) peut avoir jusqu'à 5 sessions parallèles — des conversations séparées sur le même sujet.

- **Session 1** — conversation de planification
- **Session 2** — conversation d'implémentation technique
- **Session 3** — brainstorm libre

Les sessions s'affichent sous forme d'onglets dans le panneau chat. Tape `/new` pour démarrer une nouvelle session dans le contexte actuel.

---

## Référence rapide

| Situation | Contexte à utiliser | Ce que tu peux demander |
|-----------|---------------------|-------------------------|
| Créer un nouveau projet | Général (Main Board) | "Crée un projet X" |
| Voir l'état de tous mes projets | Général | "Montre-moi mes projets" |
| Créer une carte | Projet | "Crée une carte pour Y" |
| Voir le standup | Projet | "Standup du projet" |
| Travailler sur une tâche | Carte | "Lance-toi sur cette tâche" |
| Enrichir les détails | Carte | "Enrichis cette carte" |
| Logger du temps | Carte | "J'ai passé 2h sur ça" |
| Cocher un item de checklist | Carte | "Marque 'Tests unitaires' comme fait" |
| Lancer un job planifié | Général | "Crée un job qui s'exécute chaque lundi à 9h" |
| Capturer une idée vite | N'importe lequel | "Note pour plus tard : ..." |

---

_Pour la référence technique des scopes (format de chat ID, outils disponibles par niveau, routing backend), voir [CHAT_SCOPES.md](CHAT_SCOPES.md)._
