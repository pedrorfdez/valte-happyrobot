from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = BACKEND_DIR.parent
# scripts/tunnel.sh writes the current tunnel URL here, so a new tunnel
# never needs a restart: every HR dispatch carries callback_base.
PUBLIC_URL_FILE = BACKEND_DIR / ".public_url"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(ROOT_DIR / ".env"), str(BACKEND_DIR / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    happyrobot_api_key: str = ""
    happyrobot_org_id: str = ""
    happyrobot_base_url: str = "https://platform.eu.happyrobot.ai/api/v2"
    # Bearer that HappyRobot nodes send to our callbacks.
    happyrobot_webhook_secret: str = ""
    hr_environment: str = "production"
    # hr: decide in HappyRobot. local: rule-based stand-in (offline/tests).
    # auto: HappyRobot when provisioned, local otherwise.
    valte_brain: str = "auto"
    # The proactive brain does a round this often (wall seconds) on every running crisis. 0 = never.
    # A round only costs a HappyRobot run when the sweep found something new (engine/patrol.py).
    valte_proactive_every_s: int = 45

    public_base_url: str = "http://localhost:8010"
    # Not DATABASE_URL: that one points at Supabase and is for later.
    valte_db_url: str = f"sqlite:///{BACKEND_DIR / 'valte.db'}"
    valte_sim_speed: float = 20.0
    valte_ring_timeout_s: int = 40
    valte_approval_floor_s: int = 60

    # Every outbound email is rewritten to this mailbox. Empty = send nothing.
    demo_email_to: str = ""
    # real: contacts go out through HappyRobot. dry: nothing leaves the box
    # and contacts are labelled simulated (tests, offline work).
    valte_outreach_mode: str = "real"
    exa_api_key: str = ""

    # Lets a dashboard on another device (a judge's phone, through the tunnel or the LAN) use the API. Empty = the
    # API answers only to this machine; HappyRobot callbacks and email approval links stay reachable.
    valte_dashboard_token: str = ""

    # Look up wizard-typed zone names on OpenStreetMap to place them on the map (off in tests / offline).
    valte_geocode: bool = True

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8020,http://127.0.0.1:8020,http://localhost:8030,http://127.0.0.1:8030"


settings = Settings()


def public_base_url() -> str:
    if PUBLIC_URL_FILE.exists():
        url = PUBLIC_URL_FILE.read_text().strip()
        if url:
            return url.rstrip("/")
    return settings.public_base_url.rstrip("/")
