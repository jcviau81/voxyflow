"""AI Code Review endpoint — uses the deep (Opus) model for quality analysis."""

import json
import logging
from fastapi import APIRouter
from pydantic import BaseModel

from app.services.claude_service import ClaudeService

logger = logging.getLogger(__name__)
router = APIRouter()

# Shared claude service instance (lightweight — no history, one-shot)
_claude: ClaudeService | None = None


def _get_claude() -> ClaudeService:
    global _claude
    if _claude is None:
        _claude = ClaudeService()
    return _claude


class CodeReviewRequest(BaseModel):
    code: str
    language: str = "unknown"
    context: str = ""


class CodeIssue(BaseModel):
    line: int | None = None
    severity: str  # "error" | "warning" | "info"
    message: str


class CodeReviewResponse(BaseModel):
    review: str
    issues: list[CodeIssue]
    suggestions: list[str]


_REVIEW_SYSTEM = """\
You are an expert senior software engineer performing a precise code review.
Your analysis must be helpful, specific, and actionable.
Always respond ONLY with valid JSON — no markdown fences, no extra text.

JSON schema:
{
  "review": "2-4 sentence overall assessment",
  "issues": [
    {"line": <int or null>, "severity": "error|warning|info", "message": "<issue description>"}
  ],
  "suggestions": ["<concrete improvement suggestion>", ...]
}

Rules:
- Be specific: mention variable names, line numbers when possible.
- Severity: "error" = bugs/security, "warning" = code smells/perf, "info" = style/clarity.
- Keep issues list to the most important (max 10).
- Keep suggestions actionable (max 5).
- Respond in the same language the user used for their context (default: English).
"""


@router.post("/code/review", response_model=CodeReviewResponse)
async def review_code(req: CodeReviewRequest) -> CodeReviewResponse:
    """
    Review a code snippet using the deep (Opus) model.
    Returns structured analysis: overall review, issues, and improvement suggestions.
    """
    claude = _get_claude()

    lang_note = f"Language: {req.language}" if req.language and req.language != "unknown" else ""
    ctx_note = f"Context: {req.context}" if req.context else ""
    header = "\n".join(filter(None, [lang_note, ctx_note]))

    user_prompt = (
        f"{header}\n\n```{req.language}\n{req.code}\n```"
        if header
        else f"```{req.language}\n{req.code}\n```"
    )

    try:
        raw = await claude._call_api(
            model=claude.deep_model,
            system=_REVIEW_SYSTEM,
            messages=[{"role": "user", "content": user_prompt}],
            client=claude.deep_client,
        )

        # Strip markdown fences if the model disobeyed the instruction
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = "\n".join(cleaned.split("\n")[1:])
            if cleaned.endswith("```"):
                cleaned = cleaned[: cleaned.rfind("```")]
            cleaned = cleaned.strip()

        data = json.loads(cleaned)

        issues = [
            CodeIssue(
                line=i.get("line"),
                severity=i.get("severity", "info"),
                message=i.get("message", ""),
            )
            for i in data.get("issues", [])
        ]

        return CodeReviewResponse(
            review=data.get("review", ""),
            issues=issues,
            suggestions=data.get("suggestions", []),
        )

    except json.JSONDecodeError as e:
        logger.warning(f"Code review JSON parse error: {e} — raw: {raw[:200]!r}")
        return CodeReviewResponse(
            review="Could not parse structured review. Raw output: " + raw[:500],
            issues=[],
            suggestions=[],
        )
    except Exception as e:
        logger.error(f"Code review failed: {e}")
        raise
