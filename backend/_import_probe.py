import time
t0 = time.time()
def t(): return f'{time.time()-t0:.1f}s'
print(f'[{t()}] start', flush=True)

print(f'[{t()}] config', flush=True)
from app.config import get_settings
print(f'[{t()}] database', flush=True)
from app.database import init_db, SYSTEM_MAIN_PROJECT_ID

print(f'[{t()}] importing routes...', flush=True)
from app.routes import projects, cards, techdetect, github, settings, sessions, documents, health, jobs, code, focus_sessions, mcp as mcp_routes, workspace, workers, models, worker_tasks, cli_sessions, backup, auth, debug, push
print(f'[{t()}] routes ok', flush=True)

from app.services.claude_service import ClaudeService
print(f'[{t()}] claude_service module', flush=True)

from app.services.chat_orchestration import ChatOrchestrator
print(f'[{t()}] chat_orchestration module', flush=True)

from app.services.rag_service import get_rag_service
print(f'[{t()}] rag_service module', flush=True)

from app.services.scheduler_service import get_scheduler_service
print(f'[{t()}] scheduler_service module', flush=True)

print(f'[{t()}] instantiating ClaudeService()...', flush=True)
cs = ClaudeService()
print(f'[{t()}] ClaudeService done', flush=True)

print(f'[{t()}] ChatOrchestrator(...)...', flush=True)
o = ChatOrchestrator(cs)
print(f'[{t()}] ChatOrchestrator done', flush=True)
