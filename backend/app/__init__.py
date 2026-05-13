# Voxyflow Backend

# Rewrite /proc/<pid>/cmdline so worker `pkill -f` patterns cannot match the
# supervisor by accident. Default uvicorn cmdline is
# `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`, which collides
# with any project's dev-server pkill like `pkill -f 'uvicorn app.main'`.
# Runs at import time, before any uvicorn worker or sub-process spawns.
try:
    import os as _os
    import setproctitle as _spt

    _spt.setproctitle(f"voxyflow-backend [pid={_os.getpid()}]")
except Exception:
    pass
