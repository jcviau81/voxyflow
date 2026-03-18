"""Tech stack auto-detection endpoint."""

from fastapi import APIRouter
from pathlib import Path
import json
import os

router = APIRouter(prefix="/api/tech", tags=["tech"])

# Technology detection rules
TECH_SIGNATURES = {
    # Python
    "requirements.txt": {"name": "Python", "icon": "🐍", "category": "language"},
    "setup.py": {"name": "Python", "icon": "🐍", "category": "language"},
    "pyproject.toml": {"name": "Python", "icon": "🐍", "category": "language"},
    "Pipfile": {"name": "Python (Pipenv)", "icon": "🐍", "category": "language"},

    # JavaScript/TypeScript
    "package.json": {"name": "Node.js", "icon": "💚", "category": "runtime"},
    "tsconfig.json": {"name": "TypeScript", "icon": "💙", "category": "language"},

    # Rust
    "Cargo.toml": {"name": "Rust", "icon": "🦀", "category": "language"},

    # Go
    "go.mod": {"name": "Go", "icon": "🐹", "category": "language"},

    # Docker
    "Dockerfile": {"name": "Docker", "icon": "🐳", "category": "infra"},
    "docker-compose.yml": {"name": "Docker Compose", "icon": "🐳", "category": "infra"},
    "docker-compose.yaml": {"name": "Docker Compose", "icon": "🐳", "category": "infra"},

    # CI/CD
    ".github/workflows": {"name": "GitHub Actions", "icon": "⚙️", "category": "ci"},
    ".gitlab-ci.yml": {"name": "GitLab CI", "icon": "🦊", "category": "ci"},

    # Config & Build
    ".env": {"name": "Environment Config", "icon": "🔐", "category": "config"},
    "Makefile": {"name": "Make", "icon": "🔨", "category": "build"},
    ".eslintrc.json": {"name": "ESLint", "icon": "📏", "category": "quality"},
    "jest.config.js": {"name": "Jest", "icon": "🃏", "category": "testing"},
    "playwright.config.ts": {"name": "Playwright", "icon": "🎭", "category": "testing"},
    "webpack.config.js": {"name": "Webpack", "icon": "📦", "category": "build"},
    "vite.config.ts": {"name": "Vite", "icon": "⚡", "category": "build"},
}

# Framework detection from package.json dependencies
NPM_FRAMEWORKS = {
    "react": {"name": "React", "icon": "⚛️", "category": "framework"},
    "vue": {"name": "Vue.js", "icon": "💚", "category": "framework"},
    "next": {"name": "Next.js", "icon": "▲", "category": "framework"},
    "express": {"name": "Express", "icon": "🚂", "category": "framework"},
    "fastify": {"name": "Fastify", "icon": "🏎️", "category": "framework"},
    "@playwright/test": {"name": "Playwright", "icon": "🎭", "category": "testing"},
    "jest": {"name": "Jest", "icon": "🃏", "category": "testing"},
    "typescript": {"name": "TypeScript", "icon": "💙", "category": "language"},
    "tailwindcss": {"name": "Tailwind CSS", "icon": "🌊", "category": "styling"},
    "marked": {"name": "Marked", "icon": "📝", "category": "lib"},
    "highlight.js": {"name": "Highlight.js", "icon": "🌈", "category": "lib"},
    "dompurify": {"name": "DOMPurify", "icon": "🛡️", "category": "security"},
}

# Python framework detection from requirements.txt
PIP_FRAMEWORKS = {
    "fastapi": {"name": "FastAPI", "icon": "⚡", "category": "framework"},
    "django": {"name": "Django", "icon": "🎸", "category": "framework"},
    "flask": {"name": "Flask", "icon": "🧪", "category": "framework"},
    "sqlalchemy": {"name": "SQLAlchemy", "icon": "🗄️", "category": "database"},
    "pydantic": {"name": "Pydantic", "icon": "✅", "category": "validation"},
    "pytest": {"name": "Pytest", "icon": "🧪", "category": "testing"},
    "anthropic": {"name": "Anthropic SDK", "icon": "🤖", "category": "ai"},
    "openai": {"name": "OpenAI SDK", "icon": "🤖", "category": "ai"},
    "keyring": {"name": "Keyring", "icon": "🔐", "category": "security"},
}


@router.get("/detect")
async def detect_tech(project_path: str):
    """Scan a project directory and detect technologies."""
    path = Path(os.path.expanduser(project_path))
    if not path.exists():
        return {"error": "Path not found", "technologies": []}

    techs: list[dict] = []
    seen: set[str] = set()

    # Directories to scan: root + immediate subdirectories (monorepo support)
    scan_dirs = [path]
    for child in path.iterdir():
        if child.is_dir() and child.name not in (
            "node_modules", ".git", "__pycache__", "venv", "dist", ".venv"
        ):
            scan_dirs.append(child)

    for scan_dir in scan_dirs:
        prefix = "" if scan_dir == path else f"{scan_dir.name}/"

        # Scan for signature files
        for filename, tech_info in TECH_SIGNATURES.items():
            check_path = scan_dir / filename
            if check_path.exists():
                key = tech_info["name"]
                if key not in seen:
                    techs.append({**tech_info, "source": f"{prefix}{filename}"})
                    seen.add(key)

        # Deep scan package.json
        pkg_path = scan_dir / "package.json"
        if pkg_path.exists():
            try:
                pkg = json.loads(pkg_path.read_text())
                all_deps = {
                    **pkg.get("dependencies", {}),
                    **pkg.get("devDependencies", {}),
                }
                for dep, tech_info in NPM_FRAMEWORKS.items():
                    if dep in all_deps:
                        key = tech_info["name"]
                        if key not in seen:
                            version = all_deps[dep].lstrip("^~>=")
                            techs.append(
                                {**tech_info, "version": version, "source": f"{prefix}package.json"}
                            )
                            seen.add(key)
            except Exception:
                pass

        # Deep scan requirements.txt
        req_path = scan_dir / "requirements.txt"
        if req_path.exists():
            try:
                lines = req_path.read_text().strip().split("\n")
                for line in lines:
                    pkg_name = (
                        line.split(">=")[0].split("==")[0].split("[")[0].strip().lower()
                    )
                    if pkg_name in PIP_FRAMEWORKS:
                        tech_info = PIP_FRAMEWORKS[pkg_name]
                        key = tech_info["name"]
                        if key not in seen:
                            version = (
                                line.split(">=")[-1].strip() if ">=" in line else ""
                            )
                            techs.append(
                                {
                                    **tech_info,
                                    "version": version,
                                    "source": f"{prefix}requirements.txt",
                                }
                            )
                            seen.add(key)
            except Exception:
                pass

    # Count files by extension
    file_counts: dict[str, int] = {}
    for f in path.rglob("*"):
        if f.is_file() and not any(
            p in str(f)
            for p in ["node_modules", ".git", "__pycache__", "venv", "dist"]
        ):
            ext = f.suffix.lower()
            if ext:
                file_counts[ext] = file_counts.get(ext, 0) + 1

    return {
        "path": str(path),
        "technologies": sorted(techs, key=lambda t: t["category"]),
        "file_counts": dict(sorted(file_counts.items(), key=lambda x: -x[1])[:15]),
        "total_files": sum(file_counts.values()),
    }
