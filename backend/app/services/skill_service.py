"""Skill Service — Hermes-style learned procedures (agentskills.io format).

Skills are reusable "how to do X" procedures stored as SKILL.md files:
YAML frontmatter (``name`` + ``description``) followed by a markdown body
of instructions. They form a learning loop:

- Workers distill non-obvious multi-step procedures into skills at closeout.
- Dispatchers offer to save user-described procedures as skills.
- Both see a compact catalog (name + description) in their prompt and load
  full instructions on demand via ``voxyflow.skill.get`` — progressive
  disclosure, so the prompt cost stays at catalog size.

Storage layout (under ``VOXYFLOW_DIR/skills/``):

    global/<slug>/SKILL.md                      — visible everywhere
    workspace-<workspace_uuid>/<slug>/SKILL.md  — visible in that workspace only

Workspace scoping follows the workspace-isolation invariant: directories are
keyed by the workspace **UUID** (never the title/slug), and the pseudo-ids
``""`` / ``"system-main"`` (general chat) resolve to global-only visibility.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.config import VOXYFLOW_DIR

logger = logging.getLogger(__name__)

SKILL_FILENAME = "SKILL.md"
GLOBAL_SCOPE_DIR = "global"

# Slugs: kebab-case, lowercase alphanumerics + hyphens only. Anything else
# (dots, slashes, traversal attempts) is rejected outright.
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_MAX_SLUG_LEN = 64


@dataclass
class SkillMeta:
    """Catalog entry for one skill — name + description, no body."""

    name: str
    description: str
    scope: str  # "global" | "workspace"
    path: str   # absolute path to the SKILL.md file


def sanitize_skill_name(name: str) -> str:
    """Normalize a skill name to a kebab-case slug; raise ValueError if unsafe.

    Lowercases and converts spaces/underscores to hyphens, then validates
    against ``[a-z0-9-]`` kebab-case. Path traversal ("../x"), dots, slashes
    and any other character are rejected — slugs become directory names.
    """
    slug = (name or "").strip().lower().replace(" ", "-").replace("_", "-")
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug or len(slug) > _MAX_SLUG_LEN or not _SLUG_RE.match(slug):
        raise ValueError(
            f"Invalid skill name {name!r} — use a kebab-case slug "
            "(lowercase letters, digits, hyphens; e.g. 'deploy-staging')."
        )
    return slug


def _parse_frontmatter(text: str) -> tuple[Optional[dict], str]:
    """Split SKILL.md into (frontmatter dict, body).

    Returns (None, full_text) when the frontmatter is missing or malformed —
    callers decide whether to skip (catalog) or still serve the body (get).
    """
    if not text.startswith("---"):
        return None, text
    # Frontmatter is delimited by the first two '---' lines.
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?", text, flags=re.DOTALL)
    if not match:
        return None, text
    body = text[match.end():]
    try:
        import yaml
        meta = yaml.safe_load(match.group(1))
    except Exception as e:
        logger.warning(f"[skills] Malformed YAML frontmatter: {e}")
        return None, body
    if not isinstance(meta, dict):
        return None, body
    return meta, body


def _normalize_workspace_id(workspace_id: Optional[str]) -> str:
    """Return the real workspace UUID, or "" for general chat / no scope.

    Mirrors the memory-service convention: empty or "system-main" means the
    general chat — only global skills are visible there.
    """
    pid = (workspace_id or "").strip()
    if not pid or pid == "system-main":
        return ""
    return pid


class SkillService:
    """File-backed skill store (agentskills.io SKILL.md convention)."""

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = Path(base_dir) if base_dir else (VOXYFLOW_DIR / "skills")

    # ------------------------------------------------------------------
    # Scope directories
    # ------------------------------------------------------------------

    def _scope_dir(self, scope: str, workspace_id: str = "") -> Path:
        if scope == "global":
            return self.base_dir / GLOBAL_SCOPE_DIR
        return self.base_dir / f"workspace-{workspace_id}"

    def _visible_scope_dirs(self, workspace_id: Optional[str]) -> list[tuple[str, Path]]:
        """(scope_label, dir) pairs visible from this workspace, global first."""
        dirs = [("global", self._scope_dir("global"))]
        pid = _normalize_workspace_id(workspace_id)
        if pid:
            dirs.append(("workspace", self._scope_dir("workspace", pid)))
        return dirs

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def list_skills(self, workspace_id: Optional[str] = None) -> list[SkillMeta]:
        """List skills visible from this workspace (global + workspace-scoped).

        Empty / "system-main" workspace_id = general chat = global only.
        Entries with missing or malformed frontmatter are skipped with a
        log warning (tolerant — one bad file must not break the catalog).
        """
        skills: list[SkillMeta] = []
        for scope_label, scope_dir in self._visible_scope_dirs(workspace_id):
            if not scope_dir.is_dir():
                continue
            for skill_dir in sorted(scope_dir.iterdir()):
                skill_file = skill_dir / SKILL_FILENAME
                if not skill_file.is_file():
                    continue
                try:
                    meta, _body = _parse_frontmatter(
                        skill_file.read_text(encoding="utf-8")
                    )
                except OSError as e:
                    logger.warning(f"[skills] Unreadable skill file {skill_file}: {e}")
                    continue
                if not meta or not str(meta.get("name") or "").strip():
                    logger.warning(
                        f"[skills] Skipping {skill_file} — missing/malformed frontmatter"
                    )
                    continue
                skills.append(SkillMeta(
                    name=str(meta["name"]).strip(),
                    description=str(meta.get("description") or "").strip(),
                    scope=scope_label,
                    path=str(skill_file),
                ))
        return skills

    def get_skill(self, name: str, workspace_id: Optional[str] = None) -> Optional[dict]:
        """Return {name, description, scope, instructions} or None.

        Workspace-scoped skills shadow global ones with the same name.
        """
        slug = sanitize_skill_name(name)
        # Workspace scope wins — iterate visible dirs in reverse (workspace last → checked first).
        for scope_label, scope_dir in reversed(self._visible_scope_dirs(workspace_id)):
            skill_file = scope_dir / slug / SKILL_FILENAME
            if not skill_file.is_file():
                continue
            text = skill_file.read_text(encoding="utf-8")
            meta, body = _parse_frontmatter(text)
            return {
                "name": (meta or {}).get("name") or slug,
                "description": str((meta or {}).get("description") or "").strip(),
                "scope": scope_label,
                "instructions": body.strip(),
            }
        return None

    def save_skill(
        self,
        name: str,
        description: str,
        body: str,
        scope: str = "workspace",
        workspace_id: Optional[str] = None,
    ) -> SkillMeta:
        """Create or update a skill. Returns its catalog entry.

        scope="workspace" requires a real workspace UUID; with an empty /
        "system-main" workspace the skill falls back to global (general chat
        has no per-workspace shelf).
        """
        slug = sanitize_skill_name(name)
        description = " ".join((description or "").split())
        pid = _normalize_workspace_id(workspace_id)
        if scope not in ("global", "workspace"):
            raise ValueError(f"Invalid scope {scope!r} — use 'global' or 'workspace'.")
        if scope == "workspace" and not pid:
            scope = "global"  # general chat → global shelf

        skill_dir = self._scope_dir(scope, pid)
        skill_file = skill_dir / slug / SKILL_FILENAME
        skill_file.parent.mkdir(parents=True, exist_ok=True)
        content = (
            "---\n"
            f"name: {slug}\n"
            f"description: {_yaml_quote(description)}\n"
            "---\n\n"
            f"{(body or '').strip()}\n"
        )
        skill_file.write_text(content, encoding="utf-8")
        logger.info(f"[skills] Saved skill {slug!r} scope={scope} → {skill_file}")
        return SkillMeta(name=slug, description=description, scope=scope, path=str(skill_file))

    def delete_skill(self, name: str, workspace_id: Optional[str] = None) -> bool:
        """Delete a skill (workspace scope checked first, then global)."""
        slug = sanitize_skill_name(name)
        for _scope_label, scope_dir in reversed(self._visible_scope_dirs(workspace_id)):
            skill_dir = scope_dir / slug
            skill_file = skill_dir / SKILL_FILENAME
            if not skill_file.is_file():
                continue
            skill_file.unlink()
            try:
                skill_dir.rmdir()  # only if empty — extra assets stay put
            except OSError:
                pass
            logger.info(f"[skills] Deleted skill {slug!r} from {scope_dir.name}")
            return True
        return False

    # ------------------------------------------------------------------
    # Prompt catalog (progressive disclosure — names + descriptions only)
    # ------------------------------------------------------------------

    def build_skills_catalog(
        self,
        workspace_id: Optional[str] = None,
        max_chars: int = 2500,
    ) -> Optional[str]:
        """Compact prompt block listing visible skills, or None when empty.

        Catalog only — bodies are loaded on demand via voxyflow.skill.get.
        Truncates at max_chars with a pointer to voxyflow.skill.list.
        """
        skills = self.list_skills(workspace_id)
        if not skills:
            return None

        header = (
            "## Skills (learned procedures)\n"
            "These are stored step-by-step procedures from past work. If one matches "
            "your task, call voxyflow.skill.get (name) to load its full instructions "
            "BEFORE relying on it — the catalog below only carries the summary."
        )
        lines: list[str] = [header]
        skipped = 0
        used = len(header)
        for scope_label, group_title in (("global", "Global skills:"), ("workspace", "Workspace skills:")):
            group = [s for s in skills if s.scope == scope_label]
            if not group:
                continue
            if used + len(group_title) + 1 > max_chars:
                skipped += len(group)
                continue
            lines.append(group_title)
            used += len(group_title) + 1
            for s in group:
                line = f"- {s.name}: {s.description}" if s.description else f"- {s.name}"
                if used + len(line) + 1 > max_chars:
                    skipped += 1
                    continue
                lines.append(line)
                used += len(line) + 1
        if skipped:
            lines.append(f"… and {skipped} more — call voxyflow.skill.list for the full catalog.")
        return "\n".join(lines)


def _yaml_quote(value: str) -> str:
    """Render a one-line YAML string value safely (double-quoted)."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_skill_service: Optional[SkillService] = None


def get_skill_service() -> SkillService:
    global _skill_service
    if _skill_service is None:
        _skill_service = SkillService()
    return _skill_service
