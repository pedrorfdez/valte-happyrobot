"""Which PedroD-* workflows exist in HappyRobot, as provisioned by us."""

from sqlalchemy.orm import Session

from valte.models import HrWorkflow
from valte.settings import settings

PREFIX = "PedroD-"
INGEST = {"call": "PedroD-ingest-calls", "social": "PedroD-ingest-social", "news": "PedroD-ingest-news"}
COORDINATOR = "PedroD-coordinator"
PROACTIVE = "PedroD-proactive"
COMMAND = "PedroD-crisis-command"
INTAKE = "PedroD-crisis-intake"
OUTCOME = "PedroD-crisis-response-coordination"
OUTREACH = "PedroD-outreach"
OUTREACH_CALL = "PedroD-outreach-call"
EMERGENCY_CALL = "PedroD-emergency-call"
CRISIS_START = "PedroD-crisis-start"


def get(db: Session, name: str) -> HrWorkflow | None:
    return db.get(HrWorkflow, name)


def usable(db: Session, name: str) -> bool:
    """HappyRobot does this job only if we may call it and it exists."""
    if settings.valte_brain == "local" or not settings.happyrobot_api_key:
        return False
    return get(db, name) is not None
