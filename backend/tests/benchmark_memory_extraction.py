"""B5 Benchmark: Regex vs LLM memory extraction.

Compares the old regex-only extraction (pre-B2) against the new LLM-based
extraction (B1+B2) on crafted conversations with known ground-truth memories.

Usage:
    cd backend && python -m tests.benchmark_memory_extraction
"""

import asyncio
import json
import re
import sys
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Ensure backend is on path
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ---------------------------------------------------------------------------
# Copy of the old regex patterns and _classify_text (from git history, pre-B2)
# ---------------------------------------------------------------------------

_DECISION_PATTERNS = [
    re.compile(r"(?:I|we|let'?s)\s+(?:decided?|chose?|go(?:ing)?\s+with|picked|settled\s+on)", re.I),
    re.compile(r"(?:the\s+)?decision\s+(?:is|was)\s+to", re.I),
    re.compile(r"(?:I|we)\s+(?:will|'ll)\s+(?:use|go\s+with|stick\s+with)", re.I),
]
_PREFERENCE_PATTERNS = [
    re.compile(r"(?:I|we)\s+prefer", re.I),
    re.compile(r"(?:I|we)\s+(?:like|want|need)\s+(?:to\s+)?(?:use|have|keep)", re.I),
    re.compile(r"(?:always|never|don'?t)\s+(?:use|do|want)", re.I),
]
_BUG_PATTERNS = [
    re.compile(r"(?:bug|issue|problem|error|crash|broken|fix(?:ed)?)\b", re.I),
    re.compile(r"(?:doesn'?t|does\s+not|isn'?t|is\s+not)\s+work", re.I),
]
_TECH_PATTERNS = [
    re.compile(r"(?:using|switched?\s+to|migrated?\s+to|installed?|upgraded?)\s+\w+", re.I),
    re.compile(r"(?:stack|framework|library|tool|dependency|version)\b", re.I),
]
_LESSON_PATTERNS = [
    re.compile(r"(?:lesson|learned|takeaway|insight|realized?|turns?\s+out)\b", re.I),
    re.compile(r"(?:important|remember|note\s+to\s+self)\b", re.I),
]


def _classify_text_regex(text: str) -> tuple[str, str]:
    """Old regex classifier — returns (type, importance)."""
    for pat in _DECISION_PATTERNS:
        if pat.search(text):
            return "decision", "high"
    for pat in _BUG_PATTERNS:
        if pat.search(text):
            return "fact", "high"
    for pat in _PREFERENCE_PATTERNS:
        if pat.search(text):
            return "preference", "medium"
    for pat in _TECH_PATTERNS:
        if pat.search(text):
            return "fact", "medium"
    for pat in _LESSON_PATTERNS:
        if pat.search(text):
            return "lesson", "high"
    return "context", "low"


def regex_extract(messages: list[dict]) -> list[dict]:
    """Old regex-based extraction: split sentences, classify, keep non-trivial."""
    results = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if not content or role == "system":
            continue
        sentences = re.split(r'(?<=[.!?])\s+', content)
        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 20:
                continue
            mem_type, importance = _classify_text_regex(sentence)
            if mem_type == "context" and importance == "low":
                continue
            results.append({
                "content": sentence,
                "type": mem_type,
                "importance": importance,
            })
    return results


# ---------------------------------------------------------------------------
# LLM extraction — uses the current production code
# ---------------------------------------------------------------------------

async def llm_extract(messages: list[dict]) -> list[dict]:
    """Run the current LLM extraction pipeline (haiku)."""
    from app.services.memory_service import _llm_extract_memories_standalone
    items = await _llm_extract_memories_standalone(messages)
    if items is None:
        return []
    # Apply the same confidence filter as production
    return [
        item for item in items
        if item.get("type") != "skip"
        and float(item.get("confidence", 0)) > 0.7
        and len((item.get("content") or "").strip()) >= 15
    ]


# ---------------------------------------------------------------------------
# Standalone LLM extraction (no MemoryService instance needed)
# ---------------------------------------------------------------------------
# We'll monkey-patch this into memory_service if it doesn't exist

def _ensure_standalone_extractor():
    """Make _llm_extract_memories available as a standalone function."""
    import app.services.memory_service as ms
    if hasattr(ms, "_llm_extract_memories_standalone"):
        return

    async def _standalone(messages: list[dict]) -> Optional[list[dict]]:
        try:
            from app.services.claude_service import ClaudeService
            claude = ClaudeService()
            messages_block = ms._format_messages_for_extraction(messages)
            if not messages_block.strip():
                return None
            user_prompt = ms._MEMORY_EXTRACTION_USER_TEMPLATE.format(
                messages_block=messages_block
            )
            raw = await claude._call_api(
                model=claude.haiku_model,
                system=ms._MEMORY_EXTRACTION_SYSTEM,
                messages=[{"role": "user", "content": user_prompt}],
                client=claude.haiku_client,
                client_type=claude.haiku_client_type,
                use_tools=False,
            )
            if not raw or not raw.strip():
                return None
            text = raw.strip()
            if text.startswith("```"):
                text = text.split("```", 2)[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.rsplit("```", 1)[0].strip()
            parsed = json.loads(text)
            if not isinstance(parsed, list):
                return None
            return parsed
        except Exception as e:
            print(f"  [LLM ERROR] {e}")
            return None

    ms._llm_extract_memories_standalone = _standalone


# ---------------------------------------------------------------------------
# Test conversations with ground-truth expectations
# ---------------------------------------------------------------------------

TEST_CONVERSATIONS = [
    {
        "name": "EN: Clear technical decision",
        "lang": "en",
        "messages": [
            {"role": "user", "content": "I've been comparing Redis and Memcached for our caching layer."},
            {"role": "assistant", "content": "Both are solid. Redis has richer data structures."},
            {"role": "user", "content": "We decided to go with Redis for caching. It supports pub/sub which we'll need for real-time notifications."},
            {"role": "assistant", "content": "Good choice. I'll set up the Redis client configuration."},
        ],
        "expected": [
            {"content_keywords": ["redis", "caching"], "type": "decision"},
            {"content_keywords": ["redis", "pub/sub", "notification"], "type": "fact"},
        ],
    },
    {
        "name": "FR: Préférence de style de code",
        "lang": "fr",
        "messages": [
            {"role": "user", "content": "Je préfère toujours utiliser des async/await plutôt que des callbacks. C'est plus lisible."},
            {"role": "assistant", "content": "Noté. Je vais utiliser async/await partout dans le projet."},
            {"role": "user", "content": "Aussi, ne jamais utiliser print() pour le debug — toujours logger.debug()."},
        ],
        "expected": [
            {"content_keywords": ["async", "await"], "type": "preference"},
            {"content_keywords": ["print", "logger", "debug"], "type": "preference"},
        ],
    },
    {
        "name": "EN: Bug report and fix",
        "lang": "en",
        "messages": [
            {"role": "user", "content": "There's a critical bug: the WebSocket connection drops after exactly 30 seconds of inactivity."},
            {"role": "assistant", "content": "That's the nginx proxy_read_timeout default. I fixed it by setting proxy_read_timeout 300s in the nginx config."},
            {"role": "user", "content": "Perfect, that fixed it. Good to know for future reference."},
        ],
        "expected": [
            {"content_keywords": ["websocket", "30 seconds", "drop"], "type": "fact"},
            {"content_keywords": ["nginx", "proxy_read_timeout"], "type": "lesson"},
        ],
    },
    {
        "name": "FR: Décision d'architecture",
        "lang": "fr",
        "messages": [
            {"role": "user", "content": "Pour la base de données, on va utiliser PostgreSQL avec SQLAlchemy comme ORM."},
            {"role": "assistant", "content": "Bon choix. Je configure l'async avec asyncpg comme driver."},
            {"role": "user", "content": "Oui, et on utilise Alembic pour les migrations. C'est important de toujours versionner le schéma."},
        ],
        "expected": [
            {"content_keywords": ["postgresql", "sqlalchemy"], "type": "decision"},
            {"content_keywords": ["alembic", "migration"], "type": "decision"},
        ],
    },
    {
        "name": "EN: Casual chat with no memory value",
        "lang": "en",
        "messages": [
            {"role": "user", "content": "Hey, how's it going?"},
            {"role": "assistant", "content": "All good! What would you like to work on today?"},
            {"role": "user", "content": "Not sure yet, just checking in. Maybe later."},
            {"role": "assistant", "content": "No problem, I'm here whenever you're ready."},
        ],
        "expected": [],  # Nothing worth remembering
    },
    {
        "name": "Franglais: Mixed tech discussion",
        "lang": "mixed",
        "messages": [
            {"role": "user", "content": "Le frontend est en React avec TypeScript. On a switch de JavaScript à TypeScript la semaine passée."},
            {"role": "assistant", "content": "Noté. TypeScript c'est un bon move pour la type safety."},
            {"role": "user", "content": "J'ai réalisé que les tests unitaires avec Jest sont pas suffisants — il faut aussi des tests e2e avec Playwright."},
        ],
        "expected": [
            {"content_keywords": ["react", "typescript"], "type": "fact"},
            {"content_keywords": ["javascript", "typescript", "switch"], "type": "fact"},
            {"content_keywords": ["jest", "playwright", "e2e"], "type": "lesson"},
        ],
    },
    {
        "name": "EN: Subtle preference (no trigger words)",
        "lang": "en",
        "messages": [
            {"role": "user", "content": "When you write code for me, keep functions under 30 lines. Small functions are easier to test."},
            {"role": "assistant", "content": "Understood, I'll keep functions concise."},
            {"role": "user", "content": "Also, every public function needs a docstring. No exceptions."},
        ],
        "expected": [
            {"content_keywords": ["function", "30 lines"], "type": "preference"},
            {"content_keywords": ["docstring", "public function"], "type": "preference"},
        ],
    },
    {
        "name": "FR: Lesson learned from incident",
        "lang": "fr",
        "messages": [
            {"role": "user", "content": "On a eu un incident en prod hier. Le service de mémoire crashait parce que ChromaDB n'avait plus d'espace disque."},
            {"role": "assistant", "content": "Aïe. Il faut monitorer l'espace disque de ChromaDB."},
            {"role": "user", "content": "Leçon apprise: toujours ajouter un health check qui vérifie l'espace disque disponible avant d'écrire."},
        ],
        "expected": [
            {"content_keywords": ["chromadb", "espace disque", "crash"], "type": "fact"},
            {"content_keywords": ["health check", "espace disque"], "type": "lesson"},
        ],
    },
    {
        "name": "EN: Version pinning decision",
        "lang": "en",
        "messages": [
            {"role": "user", "content": "We're pinning Python to 3.12 for this project. Don't use any 3.13 features."},
            {"role": "assistant", "content": "Got it. Python 3.12 only."},
            {"role": "user", "content": "And we'll use uv instead of pip for package management. It's way faster."},
        ],
        "expected": [
            {"content_keywords": ["python", "3.12"], "type": "decision"},
            {"content_keywords": ["uv", "pip", "package"], "type": "decision"},
        ],
    },
    {
        "name": "EN: Assistant-heavy response (noise test)",
        "lang": "en",
        "messages": [
            {"role": "assistant", "content": "I've analyzed the codebase and here's what I found. The main entry point is in app/main.py which initializes FastAPI. The routing is standard with APIRouter. There are 15 endpoint files. The database uses SQLAlchemy with async sessions. Tests use pytest with fixtures defined in conftest.py."},
            {"role": "user", "content": "Ok cool, thanks for the overview."},
        ],
        "expected": [],  # Assistant describing code = no new memory needed
    },
]


# ---------------------------------------------------------------------------
# Scoring logic
# ---------------------------------------------------------------------------

def _match_expected(extracted: list[dict], expected: list[dict]) -> dict:
    """Score extracted memories against expected ground truth.

    Returns dict with precision, recall, noise, matched details.
    """
    if not expected and not extracted:
        return {"precision": 1.0, "recall": 1.0, "noise": 0.0, "matched": [], "missed": [], "spurious": []}

    if not expected:
        return {
            "precision": 0.0,
            "recall": 1.0,  # Nothing to recall
            "noise": 1.0,
            "matched": [],
            "missed": [],
            "spurious": [e.get("content", "")[:80] for e in extracted],
        }

    if not extracted:
        return {
            "precision": 1.0,  # Nothing extracted = nothing wrong
            "recall": 0.0,
            "noise": 0.0,
            "matched": [],
            "missed": [str(e["content_keywords"]) for e in expected],
            "spurious": [],
        }

    matched = []
    missed = []
    used_extracted = set()

    for exp in expected:
        keywords = [kw.lower() for kw in exp["content_keywords"]]
        found = False
        for i, ext in enumerate(extracted):
            if i in used_extracted:
                continue
            ext_content = (ext.get("content") or "").lower()
            # Match if at least half the keywords appear in the content
            hits = sum(1 for kw in keywords if kw in ext_content)
            if hits >= max(1, len(keywords) // 2):
                matched.append({
                    "expected_keywords": exp["content_keywords"],
                    "extracted": ext.get("content", "")[:80],
                    "type_match": ext.get("type") == exp.get("type"),
                })
                used_extracted.add(i)
                found = True
                break
        if not found:
            missed.append(str(exp["content_keywords"]))

    spurious = [
        extracted[i].get("content", "")[:80]
        for i in range(len(extracted))
        if i not in used_extracted
    ]

    total_extracted = len(extracted)
    relevant_extracted = len(matched)
    total_expected = len(expected)

    precision = relevant_extracted / total_extracted if total_extracted > 0 else 1.0
    recall = relevant_extracted / total_expected if total_expected > 0 else 1.0
    noise = len(spurious) / total_extracted if total_extracted > 0 else 0.0

    return {
        "precision": precision,
        "recall": recall,
        "noise": noise,
        "matched": matched,
        "missed": missed,
        "spurious": spurious,
    }


# ---------------------------------------------------------------------------
# Load real session data
# ---------------------------------------------------------------------------

def _load_real_sessions(max_sessions: int = 3) -> list[dict]:
    """Try to load real conversation sessions from data/sessions/."""
    sessions_dir = Path(os.path.expanduser("~/voxyflow/data/sessions"))
    real = []

    for subdir in ["project", "card"]:
        d = sessions_dir / subdir
        if not d.exists():
            continue
        for f in sorted(d.glob("*.json"))[:5]:
            try:
                data = json.loads(f.read_text())
                msgs = data.get("messages", data) if isinstance(data, dict) else data
                if not isinstance(msgs, list):
                    continue
                # Filter to user/assistant messages with content
                clean = [
                    m for m in msgs
                    if isinstance(m, dict)
                    and m.get("role") in ("user", "assistant")
                    and m.get("content", "").strip()
                    and len(m.get("content", "")) > 20
                    and not m.get("content", "").startswith("[CARD EXECUTION]")
                    and not m.get("content", "").startswith("[PREVIOUS CARDS")
                ]
                if len(clean) >= 3:
                    real.append({
                        "name": f"Real: {f.stem[:30]}",
                        "lang": "unknown",
                        "messages": clean[-6:],  # Last 6 messages
                        "expected": None,  # No ground truth — qualitative only
                    })
                    if len(real) >= max_sessions:
                        return real
            except Exception:
                continue
    return real


# ---------------------------------------------------------------------------
# Main benchmark runner
# ---------------------------------------------------------------------------

async def run_benchmark():
    _ensure_standalone_extractor()

    print("=" * 70)
    print("B5 BENCHMARK: Regex vs LLM Memory Extraction")
    print("=" * 70)
    print()

    results = []
    real_sessions = _load_real_sessions(3)
    all_convos = TEST_CONVERSATIONS + real_sessions

    regex_total_time = 0.0
    llm_total_time = 0.0

    for i, convo in enumerate(all_convos, 1):
        name = convo["name"]
        messages = convo["messages"]
        expected = convo.get("expected")
        is_real = expected is None

        print(f"[{i}/{len(all_convos)}] {name}")

        # --- Regex extraction ---
        t0 = time.time()
        regex_out = regex_extract(messages)
        regex_time = time.time() - t0
        regex_total_time += regex_time

        # --- LLM extraction ---
        t0 = time.time()
        try:
            llm_out = await llm_extract(messages)
        except Exception as e:
            print(f"  LLM FAILED: {e}")
            llm_out = []
        llm_time = time.time() - t0
        llm_total_time += llm_time

        # --- Scoring ---
        if not is_real:
            regex_score = _match_expected(regex_out, expected)
            llm_score = _match_expected(llm_out, expected)
        else:
            regex_score = None
            llm_score = None

        result = {
            "name": name,
            "lang": convo["lang"],
            "is_real": is_real,
            "n_messages": len(messages),
            "regex": {
                "extracted": regex_out,
                "count": len(regex_out),
                "time_ms": round(regex_time * 1000, 1),
                "score": regex_score,
            },
            "llm": {
                "extracted": llm_out,
                "count": len(llm_out),
                "time_ms": round(llm_time * 1000, 1),
                "score": llm_score,
            },
            "expected_count": len(expected) if expected else "N/A",
        }
        results.append(result)

        # Quick console summary
        if not is_real:
            print(f"  Regex: {len(regex_out)} extracted, P={regex_score['precision']:.0%} R={regex_score['recall']:.0%} N={regex_score['noise']:.0%} ({regex_time*1000:.0f}ms)")
            print(f"  LLM:   {len(llm_out)} extracted, P={llm_score['precision']:.0%} R={llm_score['recall']:.0%} N={llm_score['noise']:.0%} ({llm_time*1000:.0f}ms)")
        else:
            print(f"  Regex: {len(regex_out)} extracted ({regex_time*1000:.0f}ms)")
            print(f"  LLM:   {len(llm_out)} extracted ({llm_time*1000:.0f}ms)")
        print()

    # --- Generate markdown report ---
    report = _generate_report(results, regex_total_time, llm_total_time)
    report_path = Path(__file__).parent / "benchmark_results_b5.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"Report written to {report_path}")
    print()

    return results, report


def _generate_report(results: list[dict], regex_total_time: float, llm_total_time: float) -> str:
    """Generate a markdown report from benchmark results."""
    lines = []
    lines.append("# B5 Benchmark: Regex vs LLM Memory Extraction")
    lines.append("")
    lines.append(f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"**Conversations tested**: {len(results)} ({sum(1 for r in results if not r['is_real'])} crafted, {sum(1 for r in results if r['is_real'])} real)")
    lines.append("")

    # --- Overall summary ---
    crafted = [r for r in results if not r["is_real"]]
    if crafted:
        avg_regex_p = sum(r["regex"]["score"]["precision"] for r in crafted) / len(crafted)
        avg_regex_r = sum(r["regex"]["score"]["recall"] for r in crafted) / len(crafted)
        avg_regex_n = sum(r["regex"]["score"]["noise"] for r in crafted) / len(crafted)

        avg_llm_p = sum(r["llm"]["score"]["precision"] for r in crafted) / len(crafted)
        avg_llm_r = sum(r["llm"]["score"]["recall"] for r in crafted) / len(crafted)
        avg_llm_n = sum(r["llm"]["score"]["noise"] for r in crafted) / len(crafted)

        lines.append("## Overall Summary (Crafted Conversations)")
        lines.append("")
        lines.append("| Metric | Regex | LLM | Winner |")
        lines.append("|--------|-------|-----|--------|")

        p_winner = "LLM" if avg_llm_p > avg_regex_p else ("Regex" if avg_regex_p > avg_llm_p else "Tie")
        r_winner = "LLM" if avg_llm_r > avg_regex_r else ("Regex" if avg_regex_r > avg_llm_r else "Tie")
        n_winner = "LLM" if avg_llm_n < avg_regex_n else ("Regex" if avg_regex_n < avg_llm_n else "Tie")

        lines.append(f"| **Precision** | {avg_regex_p:.0%} | {avg_llm_p:.0%} | {p_winner} |")
        lines.append(f"| **Recall** | {avg_regex_r:.0%} | {avg_llm_r:.0%} | {r_winner} |")
        lines.append(f"| **Noise** | {avg_regex_n:.0%} | {avg_llm_n:.0%} | {n_winner} |")
        lines.append(f"| **Total time** | {regex_total_time*1000:.0f}ms | {llm_total_time*1000:.0f}ms | {'Regex' if regex_total_time < llm_total_time else 'LLM'} |")
        lines.append("")

    # --- Per-conversation breakdown ---
    lines.append("## Per-Conversation Breakdown")
    lines.append("")
    lines.append("| # | Conversation | Lang | Expected | Regex (P/R/N) | LLM (P/R/N) | Regex count | LLM count |")
    lines.append("|---|-------------|------|----------|---------------|-------------|-------------|-----------|")

    for i, r in enumerate(results, 1):
        name = r["name"][:35]
        lang = r["lang"]
        exp = r["expected_count"]

        if not r["is_real"]:
            rs = r["regex"]["score"]
            ls = r["llm"]["score"]
            regex_prn = f"{rs['precision']:.0%}/{rs['recall']:.0%}/{rs['noise']:.0%}"
            llm_prn = f"{ls['precision']:.0%}/{ls['recall']:.0%}/{ls['noise']:.0%}"
        else:
            regex_prn = "—"
            llm_prn = "—"

        lines.append(f"| {i} | {name} | {lang} | {exp} | {regex_prn} | {llm_prn} | {r['regex']['count']} | {r['llm']['count']} |")

    lines.append("")

    # --- Detailed results ---
    lines.append("## Detailed Results")
    lines.append("")

    for i, r in enumerate(results, 1):
        lines.append(f"### {i}. {r['name']}")
        lines.append("")

        # Regex extracted
        lines.append("**Regex extracted:**")
        if r["regex"]["extracted"]:
            for e in r["regex"]["extracted"]:
                lines.append(f"- [{e.get('type','?')}] {e.get('content','')[:100]}")
        else:
            lines.append("- _(nothing)_")
        lines.append("")

        # LLM extracted
        lines.append("**LLM extracted:**")
        if r["llm"]["extracted"]:
            for e in r["llm"]["extracted"]:
                conf = f" (conf={e.get('confidence','?')})" if "confidence" in e else ""
                lines.append(f"- [{e.get('type','?')}] {e.get('content','')[:100]}{conf}")
        else:
            lines.append("- _(nothing)_")
        lines.append("")

        if not r["is_real"] and r["llm"]["score"]:
            ls = r["llm"]["score"]
            rs = r["regex"]["score"]
            if ls["missed"]:
                lines.append(f"**LLM missed:** {', '.join(ls['missed'])}")
            if rs["missed"]:
                lines.append(f"**Regex missed:** {', '.join(rs['missed'])}")
            if ls["spurious"]:
                lines.append(f"**LLM noise:** {'; '.join(ls['spurious'])}")
            if rs["spurious"]:
                lines.append(f"**Regex noise:** {'; '.join(rs['spurious'])}")
            lines.append("")

    # --- Verdict ---
    lines.append("## Verdict")
    lines.append("")

    if crafted:
        # Compute F1 for overall comparison
        regex_f1 = 2 * avg_regex_p * avg_regex_r / (avg_regex_p + avg_regex_r) if (avg_regex_p + avg_regex_r) > 0 else 0
        llm_f1 = 2 * avg_llm_p * avg_llm_r / (avg_llm_p + avg_llm_r) if (avg_llm_p + avg_llm_r) > 0 else 0

        lines.append(f"| | Regex | LLM |")
        lines.append(f"|---|-------|-----|")
        lines.append(f"| F1 Score | {regex_f1:.0%} | {llm_f1:.0%} |")
        lines.append(f"| Avg Precision | {avg_regex_p:.0%} | {avg_llm_p:.0%} |")
        lines.append(f"| Avg Recall | {avg_regex_r:.0%} | {avg_llm_r:.0%} |")
        lines.append(f"| Avg Noise | {avg_regex_n:.0%} | {avg_llm_n:.0%} |")
        lines.append(f"| Total Latency | {regex_total_time*1000:.0f}ms | {llm_total_time*1000:.0f}ms |")
        lines.append("")

        if llm_f1 > regex_f1:
            delta = llm_f1 - regex_f1
            lines.append(f"**LLM extraction wins** with F1 {llm_f1:.0%} vs {regex_f1:.0%} (Δ={delta:+.0%}).")
        elif regex_f1 > llm_f1:
            delta = regex_f1 - llm_f1
            lines.append(f"**Regex extraction wins** with F1 {regex_f1:.0%} vs {llm_f1:.0%} (Δ={delta:+.0%}).")
        else:
            lines.append("**Tie** — both methods have identical F1 scores.")

        lines.append("")
        lines.append("**Key observations:**")
        if avg_llm_r > avg_regex_r:
            lines.append(f"- LLM has better recall ({avg_llm_r:.0%} vs {avg_regex_r:.0%}) — catches more of the expected memories")
        if avg_llm_p > avg_regex_p:
            lines.append(f"- LLM has better precision ({avg_llm_p:.0%} vs {avg_regex_p:.0%}) — less irrelevant output")
        if avg_llm_n < avg_regex_n:
            lines.append(f"- LLM produces less noise ({avg_llm_n:.0%} vs {avg_regex_n:.0%})")
        if avg_regex_n < avg_llm_n:
            lines.append(f"- Regex produces less noise ({avg_regex_n:.0%} vs {avg_llm_n:.0%})")
        if llm_total_time > regex_total_time * 10:
            lines.append(f"- LLM is ~{llm_total_time/max(regex_total_time, 0.001):.0f}x slower (expected — API calls vs local regex)")
        lines.append(f"- B4 cost optimization (throttle + regex pre-filter) mitigates LLM latency in production")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(run_benchmark())
