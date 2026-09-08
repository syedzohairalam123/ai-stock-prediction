import os
import sys
import tempfile
from pathlib import Path

# Isolate the test database from any real dev database — must happen before
# `app.config`/`app.db` are imported anywhere, since Settings() reads the env
# once at import time. conftest.py is collected first, so this is safe.
_TEST_DB_PATH = Path(tempfile.gettempdir()) / "neural_market_test.db"
_TEST_DB_PATH.unlink(missing_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_PATH}"
# The rate limiter's state lives on the shared app instance for the whole test
# session (many tests reuse `from app.main import app`) — a low limit here
# would make the test suite's pass/fail depend on how many tests exist, not
# on correctness. Rate limiting is a production concern; keep it out of the way here.
os.environ["RATE_LIMIT_MAX_REQUESTS"] = "100000"

# Make sure `backend/` (the parent of `app/`) is importable as a package root,
# regardless of the directory pytest is invoked from.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
