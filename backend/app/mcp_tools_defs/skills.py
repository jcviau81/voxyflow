"""Skill tool defs — learned procedures (agentskills.io SKILL.md format).

Pure data — every entry follows the schema documented in ``app.mcp_tool_defs``.
Workspace scope is enforced by VOXYFLOW_WORKSPACE_ID env var at runtime; the
LLM cannot override it — workspace_id is deliberately NOT in any schema.

These tools are intentionally NOT consolidated into a _TOOL_GROUPS action enum:
they mirror the memory.* tools, which stay flat (the consolidator groups
kanban-style CRUD families, not the memory/skill singleton sets).
"""

from __future__ import annotations


SKILL_TOOLS: list[dict] = [
    {
        "name": "voxyflow.skill.list",
        "description": (
            "List available skills (learned step-by-step procedures) — global "
            "skills plus this workspace's skills. Returns name + description "
            "per skill; load full instructions with voxyflow.skill.get."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
        "_handler": "skill_list",
        "_scope": "voxyflow",
    },
    {
        "name": "voxyflow.skill.get",
        "description": (
            "Load a skill's full instructions (the SKILL.md body). Always do "
            "this BEFORE relying on a skill from the catalog — the catalog "
            "only carries the one-line description."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string", "description": "Skill slug (kebab-case, from voxyflow.skill.list)"},
            },
        },
        "_handler": "skill_get",
        "_scope": "voxyflow",
    },
    {
        "name": "voxyflow.skill.save",
        "description": (
            "Create or update a skill — a reusable 'how to do X' procedure that "
            "future tasks (dispatcher and workers) will see in their catalog. "
            "Use when the user describes a repeatable procedure/preference, or "
            "after completing a non-obvious multi-step task worth distilling. "
            "Prefer updating an existing skill over creating a near-duplicate."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["name", "description", "instructions"],
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Kebab-case slug (lowercase letters, digits, hyphens — e.g. 'deploy-staging')",
                },
                "description": {
                    "type": "string",
                    "description": "One or two sentences — shown in the catalog and used for matching",
                },
                "instructions": {
                    "type": "string",
                    "description": "Markdown body: concise step-by-step instructions (commands, gotchas, exact paths)",
                },
                "scope": {
                    "type": "string",
                    "enum": ["global", "workspace"],
                    "description": (
                        "Where the skill applies. 'workspace' (default) = this workspace only; "
                        "'global' = every workspace. In general chat, saves are global."
                    ),
                },
            },
        },
        "_handler": "skill_save",
        "_scope": "voxyflow",
    },
    {
        "name": "voxyflow.skill.delete",
        "description": "Delete a skill by name (workspace scope checked first, then global).",
        "inputSchema": {
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string", "description": "Skill slug to delete"},
            },
        },
        "_handler": "skill_delete",
        "_scope": "voxyflow",
    },
]
