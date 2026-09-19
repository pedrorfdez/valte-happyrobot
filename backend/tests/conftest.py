import os
import tempfile

# Settings are read at import time: point the app at a throwaway DB and keep
# every side effect inside the process before anything from valte is imported.
_tmp = tempfile.mkdtemp(prefix="valte-test-")
os.environ["VALTE_DB_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["VALTE_BRAIN"] = "local"
os.environ["VALTE_OUTREACH_MODE"] = "dry"
os.environ["HAPPYROBOT_WEBHOOK_SECRET"] = "test-secret"
os.environ["VALTE_APPROVAL_FLOOR_S"] = "0"
os.environ["VALTE_GEOCODE"] = "0"  # no network in tests

import pytest  # noqa: E402

from valte.db import init_db, session_scope  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _db():
    init_db()


@pytest.fixture
def crisis_id():
    from valte.core import world

    with session_scope() as db:
        c = world.create_crisis(db, {"pack": "riada-paiporta"})
        world.start_crisis(db, c)
        return c.id
