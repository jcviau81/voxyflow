"""Memory Service — reads/writes to ~/voxyflow/personality/ for Voxy's own memory."""

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

WORKSPACE_DIR = Path(os.environ.get("VOXYFLOW_DIR", os.path.expanduser("~/voxyflow"))) / "personality"
MEMORY_FILE = WORKSPACE_DIR / "MEMORY.md"
MEMORY_DIR = WORKSPACE_DIR / "memory"


class MemoryService:
    """
    Reads and writes to the OpenClaw workspace memory system.

    Memory hierarchy:
    - MEMORY.md — long-term curated memories (loaded for context)
    - memory/YYYY-MM-DD.md — daily logs (recent days loaded for context)
    - memory/projects/<name>.md — project-specific notes

    This is the shared source of truth between Ember (OpenClaw) and Voxyflow.
    """

    def __init__(self, max_memory_chars: int = 4000, daily_lookback_days: int = 3):
        self.max_memory_chars = max_memory_chars
        self.daily_lookback_days = daily_lookback_days

    def load_long_term_memory(self) -> str:
        """Load MEMORY.md — curated long-term memories."""
        if not MEMORY_FILE.exists():
            return ""
        try:
            content = MEMORY_FILE.read_text(encoding="utf-8").strip()
            # Truncate if too large (take the most recent entries — bottom of file)
            if len(content) > self.max_memory_chars:
                content = "...[earlier memories truncated]...\n" + content[-self.max_memory_chars:]
            return content
        except Exception as e:
            logger.warning(f"Failed to read MEMORY.md: {e}")
            return ""

    def load_daily_logs(self, days: Optional[int] = None) -> str:
        """Load recent daily logs for context."""
        days = days or self.daily_lookback_days
        if not MEMORY_DIR.exists():
            return ""

        now = datetime.now(timezone.utc)
        entries = []

        for i in range(days):
            from datetime import timedelta
            date = now - timedelta(days=i)
            date_str = date.strftime("%Y-%m-%d")
            daily_file = MEMORY_DIR / f"{date_str}.md"
            if daily_file.exists():
                try:
                    content = daily_file.read_text(encoding="utf-8").strip()
                    # Keep reasonable size per day
                    if len(content) > 1500:
                        content = content[-1500:]
                    entries.append(f"### {date_str}\n{content}")
                except Exception as e:
                    logger.warning(f"Failed to read {daily_file}: {e}")

        return "\n\n".join(entries)

    def load_project_memory(self, project_name: str) -> str:
        """Load project-specific memory notes if they exist."""
        project_file = MEMORY_DIR / "projects" / f"{project_name}.md"
        if not project_file.exists():
            # Try slugified version
            slug = project_name.lower().replace(" ", "-").replace("_", "-")
            project_file = MEMORY_DIR / "projects" / f"{slug}.md"

        if not project_file.exists():
            return ""

        try:
            content = project_file.read_text(encoding="utf-8").strip()
            if len(content) > 2000:
                content = content[-2000:]
            return content
        except Exception as e:
            logger.warning(f"Failed to read project memory {project_file}: {e}")
            return ""

    def build_memory_context(
        self,
        project_name: Optional[str] = None,
        include_long_term: bool = True,
        include_daily: bool = True,
    ) -> Optional[str]:
        """
        Build a combined memory context string for injection into system prompts.
        Returns None if no memory available.
        """
        sections = []

        if include_long_term:
            ltm = self.load_long_term_memory()
            if ltm:
                sections.append(f"**Long-term memory:**\n{ltm}")

        if include_daily:
            daily = self.load_daily_logs()
            if daily:
                sections.append(f"**Recent daily logs:**\n{daily}")

        if project_name:
            proj = self.load_project_memory(project_name)
            if proj:
                sections.append(f"**Project notes ({project_name}):**\n{proj}")

        if not sections:
            return None

        return "\n\n---\n\n".join(sections)

    async def append_to_daily_log(self, content: str, date: Optional[datetime] = None) -> bool:
        """
        Append an entry to today's daily log.
        Used to record decisions, learnings, and significant events from Voxyflow sessions.
        """
        date = date or datetime.now(timezone.utc)
        date_str = date.strftime("%Y-%m-%d")
        daily_file = MEMORY_DIR / f"{date_str}.md"

        try:
            MEMORY_DIR.mkdir(parents=True, exist_ok=True)
            time_str = date.strftime("%H:%M")

            if daily_file.exists():
                existing = daily_file.read_text(encoding="utf-8")
                new_content = f"{existing}\n\n**{time_str} [Voxyflow]** {content}"
            else:
                new_content = f"# {date_str}\n\n**{time_str} [Voxyflow]** {content}"

            daily_file.write_text(new_content, encoding="utf-8")
            logger.info(f"Appended to daily log: {daily_file}")
            return True
        except Exception as e:
            logger.error(f"Failed to write daily log: {e}")
            return False

    async def update_project_memory(self, project_name: str, content: str) -> bool:
        """Update or create a project-specific memory file."""
        slug = project_name.lower().replace(" ", "-").replace("_", "-")
        project_dir = MEMORY_DIR / "projects"
        project_file = project_dir / f"{slug}.md"

        try:
            project_dir.mkdir(parents=True, exist_ok=True)
            project_file.write_text(content, encoding="utf-8")
            logger.info(f"Updated project memory: {project_file}")
            return True
        except Exception as e:
            logger.error(f"Failed to update project memory: {e}")
            return False

    def search_memory(self, query: str, max_results: int = 5) -> list[dict]:
        """
        Simple keyword-based memory search across all memory files.

        MVP: substring matching with relevance scoring.
        Future: semantic search with embeddings.
        """
        results = []
        query_lower = query.lower()
        query_terms = query_lower.split()

        # Search all .md files in memory/
        if not MEMORY_DIR.exists():
            return results

        for md_file in sorted(MEMORY_DIR.rglob("*.md"), reverse=True):
            try:
                content = md_file.read_text(encoding="utf-8")
                content_lower = content.lower()

                # Score: how many query terms appear
                hits = sum(1 for term in query_terms if term in content_lower)
                if hits == 0:
                    continue

                score = hits / len(query_terms)

                # Extract relevant snippet (first paragraph containing a match)
                snippet = ""
                for para in content.split("\n\n"):
                    if any(term in para.lower() for term in query_terms):
                        snippet = para.strip()[:300]
                        break

                results.append({
                    "file": str(md_file.relative_to(WORKSPACE_DIR)),
                    "score": score,
                    "snippet": snippet,
                })
            except Exception:
                continue

        # Also search MEMORY.md
        if MEMORY_FILE.exists():
            try:
                content = MEMORY_FILE.read_text(encoding="utf-8")
                content_lower = content.lower()
                hits = sum(1 for term in query_terms if term in content_lower)
                if hits > 0:
                    score = hits / len(query_terms)
                    for para in content.split("\n\n"):
                        if any(term in para.lower() for term in query_terms):
                            snippet = para.strip()[:300]
                            results.append({
                                "file": "MEMORY.md",
                                "score": score,
                                "snippet": snippet,
                            })
                            break
            except Exception:
                pass

        # Sort by score descending, take top N
        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:max_results]


# Module-level singleton
_memory_service: Optional[MemoryService] = None


def get_memory_service() -> MemoryService:
    global _memory_service
    if _memory_service is None:
        _memory_service = MemoryService()
    return _memory_service
