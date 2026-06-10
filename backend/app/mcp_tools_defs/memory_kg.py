"""Memory, knowledge base, undo journal, and knowledge graph tool defs.

Extracted verbatim from ``app/mcp_tool_defs.py`` (H8 monolith split).
Pure data — every entry follows the schema documented in ``app.mcp_tool_defs``.
"""

from __future__ import annotations


MEMORY_KG_TOOLS: list[dict] = [
    # ---- Memory (semantic search across all memory) -------------------------
    {
        "name": "memory.search",
        "description": (
            "Search long-term memory. Default scope is the current workspace only "
            "(isolation preserved). Pass `scope='global'` for the shared global "
            "collection or `scope='other:<workspace_id>'` to query a specific other "
            "workspace explicitly — only use a cross-workspace scope when the user "
            "asks for it (e.g. \"check what was said in workspace X about Y\")."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "description": "Default 10"},
                "offset": {"type": "integer", "description": "Default 0"},
                "scope": {
                    "type": "string",
                    "description": (
                        "Retrieval scope. 'current' (default) = this workspace only. "
                        "'global' = shared cross-workspace memory. "
                        "'other:<workspace_id>' = one specific other workspace. "
                        "'current+global' = this workspace plus global."
                    ),
                },
            },
        },
        "_handler": "memory_search",
        "_scope": "voxyflow",
    },

    # ---- Memory Save (write to long-term memory) ----------------------------
    # Scope is enforced by VOXYFLOW_WORKSPACE_ID env var at runtime. The LLM
    # cannot override it — workspace_id is deliberately NOT in the schema.
    {
        "name": "memory.save",
        "description": (
            "Save a fact, decision, preference, lesson, or procedure to long-term "
            "memory (auto-scoped to current workspace). Use `type='procedure'` for "
            "reusable 'how to do X' workflows — the content should start with "
            "\"How to {task}:\" and list ≥2 ordered steps. Procedures are surfaced "
            "in a dedicated block above regular retrieval. "
            "Set `speaker='user'` when recording something the user said (verbatim "
            "or a direct paraphrase); set `speaker='assistant'` (default) for your "
            "own statement, decision, or inference. Getting the speaker right "
            "matters — it drives how the memory is attributed back to you at "
            "retrieval time, so never store a user's quote as your own."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["text"],
            "properties": {
                "text": {"type": "string"},
                "type": {
                    "type": "string",
                    "enum": ["decision", "preference", "lesson", "fact", "context", "procedure"],
                },
                "importance": {
                    "type": "string",
                    "enum": ["high", "medium", "low"],
                },
                "speaker": {
                    "type": "string",
                    "enum": ["user", "assistant"],
                    "description": (
                        "Who originated this content. 'user' = the human said it; "
                        "'assistant' = you (the bot) said or inferred it. "
                        "Defaults to 'assistant' when omitted."
                    ),
                },
            },
        },
        "_handler": "memory_save",
        "_scope": "voxyflow",
    },

    # ---- Knowledge Base (on-demand RAG) ------------------------------------
    # Scope is enforced by VOXYFLOW_WORKSPACE_ID env var at runtime.
    {
        "name": "knowledge.search",
        "description": "Search the current workspace's knowledge base (RAG) for background context.",
        "inputSchema": {
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string"},
            },
        },
        "_handler": "knowledge_search",
        "_scope": "voxyflow",
    },

    # ---- Memory Delete --------------------------------------------------------
    {
        "name": "memory.delete",
        "description": (
            "Delete a memory entry by ID. By default cascades across every "
            "collection in the current scope (same set as memory.search "
            "scope=current), so duplicate copies cannot be left behind. Use "
            "memory.search first to find the ID. Returns deleted_from (list "
            "of collections actually affected) and count."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["id"],
            "properties": {
                "id": {"type": "string", "description": "Memory document ID to delete"},
                "collection": {
                    "type": "string",
                    "description": (
                        "Optional. If set, deletes from this single collection only. "
                        "If omitted, cascades across every collection in the current scope."
                    ),
                },
            },
        },
        "_handler": "memory_delete",
        "_scope": "voxyflow",
    },

    # ---- Undo journal (reversible actions taken this chat) -------------------
    {
        "name": "voxyflow.undo.list",
        "description": (
            "List recent reversible actions taken during this chat (card.create, "
            "card.archive, card.duplicate, memory.save). Each entry carries an "
            "id you can pass to voxyflow.undo.apply to revert it. Entries TTL "
            "after 30 minutes. Use when the user asks 'annule ça' or before "
            "offering a revert option."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max entries to return (default 5, max 20)"},
            },
        },
        "_handler": "undo_list",
        "_scope": "voxyflow",
    },
    {
        "name": "voxyflow.undo.apply",
        "description": (
            "Undo a recent reversible action by replaying its inverse. If `id` "
            "is omitted, undoes the most recent action. On success the entry "
            "is consumed (a re-do is not automatic)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Undo entry id from voxyflow.undo.list (omit for most recent)"},
            },
        },
        "_handler": "undo_apply",
        "_scope": "voxyflow",
    },

    # ---- Memory Get (recent session history) ----------------------------------
    {
        "name": "memory.get",
        "description": "List recent chat sessions with their title, last message, and message count. Use to recall what was discussed in previous conversations or find a specific past session.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Number of recent sessions to return (default 10, max 50)"},
            },
        },
        "_handler": "memory_get",
        "_scope": "voxyflow",
    },

    # ---- Knowledge Graph -----------------------------------------------------
    {
        "name": "kg.add",
        "description": "Add an entity to the workspace knowledge graph, optionally with relationships and attributes. Use this to record named things (people, technologies, components, decisions) and how they relate. Relationships and attributes are created as current facts (valid_from=now, valid_to=NULL). To supersede a fact later, invalidate the old one with kg.invalidate and add the new one.",
        "inputSchema": {
            "type": "object",
            "required": ["entity_name", "entity_type"],
            "properties": {
                "entity_name": {"type": "string", "description": "Name of the entity (e.g. 'Redis', 'auth-service', 'Alice')"},
                "entity_type": {
                    "type": "string",
                    "enum": ["person", "technology", "component", "concept", "decision"],
                    "description": "Category of the entity",
                },
                "relationships": {
                    "type": "array",
                    "description": "Optional relationships to other entities",
                    "items": {
                        "type": "object",
                        "required": ["predicate", "target", "target_type"],
                        "properties": {
                            "predicate": {"type": "string", "description": "Relationship verb (e.g. 'uses', 'depends_on', 'created_by')"},
                            "target": {"type": "string", "description": "Name of the target entity"},
                            "target_type": {
                                "type": "string",
                                "enum": ["person", "technology", "component", "concept", "decision"],
                                "description": "Type of the target entity",
                            },
                        },
                    },
                },
                "attributes": {
                    "type": "array",
                    "description": "Optional key-value attributes on the entity",
                    "items": {
                        "type": "object",
                        "required": ["key", "value"],
                        "properties": {
                            "key": {"type": "string", "description": "Attribute key (e.g. 'version', 'status', 'pinned')"},
                            "value": {"type": "string", "description": "Attribute value"},
                        },
                    },
                },
            },
        },
        "_handler": "kg_add",
        "_scope": "voxyflow",
    },
    {
        "name": "kg.query",
        "description": "Search entities and their relationships in the workspace knowledge graph. Returns entities matching the filter, optionally with their active (non-invalidated) relationships. Use as_of to see which relationships existed at a past point in time.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Filter by entity name (partial match)"},
                "entity_type": {
                    "type": "string",
                    "enum": ["person", "technology", "component", "concept", "decision"],
                    "description": "Filter by entity type",
                },
                "as_of": {"type": "string", "description": "ISO datetime — show relationships that existed at this point in time (filters to valid_from <= as_of AND still active). Default: now (current state only)"},
                "include_relationships": {"type": "boolean", "description": "Include active relationships in results (default: true)"},
                "limit": {"type": "integer", "description": "Max results (default 20)"},
            },
        },
        "_handler": "kg_query",
        "_scope": "voxyflow",
    },
    {
        "name": "kg.timeline",
        "description": "Get chronological history of knowledge graph changes for a workspace or entity. Unlike kg.query (which returns only current/active facts), timeline shows ALL facts — both current (valid_to=null) and historical (valid_to set) — ordered newest-first. Use this to answer 'when did we decide X?' or 'what changed?'.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_name": {"type": "string", "description": "Filter timeline to a specific entity (partial match)"},
                "limit": {"type": "integer", "description": "Max events (default 50)"},
            },
        },
        "_handler": "kg_timeline",
        "_scope": "voxyflow",
    },
    {
        "name": "kg.invalidate",
        "description": "Mark a relationship or attribute as no longer valid by setting valid_to=now(), closing the [valid_from, valid_to) interval. The fact becomes historical — it still appears in kg.timeline but is excluded from kg.query and kg.stats. Use this when a fact has changed or been superseded (e.g. 'workspace no longer uses Redis'). Idempotent: invalidating an already-closed fact returns success=false.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "triple_id": {"type": "string", "description": "ID of the relationship triple to invalidate"},
                "attribute_id": {"type": "string", "description": "ID of the attribute to invalidate"},
            },
        },
        "_handler": "kg_invalidate",
        "_scope": "voxyflow",
    },
    {
        "name": "kg.stats",
        "description": "Get knowledge graph statistics for the current workspace — entity count, active (non-invalidated) triples, and active attributes. Historical/invalidated facts are not counted.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
        "_handler": "kg_stats",
        "_scope": "voxyflow",
    },
]
