import os
from pathlib import Path
from pydantic import BaseModel
from dotenv import load_dotenv

# Load .env if present
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True, parents=True)
UPLOADS_DIR = DATA_DIR / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True, parents=True)

DB_PATH = DATA_DIR / "obrigado.db"

class Settings(BaseModel):
    # App Settings
    app_name: str = "Obrigado"
    app_version: str = "1.0.0"
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8000"))
    debug: bool = os.getenv("DEBUG", "false").lower() in ("true", "1", "yes")

    # Timezone
    user_timezone: str = os.getenv("USER_TIMEZONE", "Europe/London")

    # Gemini API
    gemini_api_key: str = (
        os.getenv("GEMINI_API_KEY") 
        or os.getenv("GOOGLE_API_KEY") 
        or ""
    )
    llm_model: str = os.getenv("GEMINI_LLM_MODEL", "gemini-3.8-flash")
    embedding_model: str = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-2")

    # OpenRouter API
    openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
    openrouter_model: str = os.getenv("OPENROUTER_MODEL", "anthropic/claude-3.5-sonnet")
    openrouter_base_url: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

    # Provider Mode: "auto", "gemini", "openrouter", "hybrid"
    llm_provider: str = os.getenv("LLM_PROVIDER", "auto")

    # Briefing Schedules (24h format HH:MM)
    morning_briefing_time: str = os.getenv("MORNING_BRIEFING_TIME", "08:00")
    evening_briefing_time: str = os.getenv("EVENING_BRIEFING_TIME", "19:30")

    # Google Calendar
    google_client_secrets_file: str = os.getenv(
        "GOOGLE_CLIENT_SECRETS_FILE", 
        str(DATA_DIR / "credentials.json")
    )
    google_token_file: str = os.getenv(
        "GOOGLE_TOKEN_FILE", 
        str(DATA_DIR / "token.json")
    )
    calendar_auto_sync: bool = os.getenv("CALENDAR_AUTO_SYNC", "true").lower() in ("true", "1", "yes")

    # Security & Authentication (Google OAuth2)
    auth_enabled: bool = os.getenv("AUTH_ENABLED", "true").lower() in ("true", "1", "yes")
    dev_mode: bool = os.getenv("DEV_MODE", "true").lower() in ("true", "1", "yes")
    dev_user_email: str = os.getenv("DEV_USER_EMAIL", "dev@obrigado.local")
    dev_user_name: str = os.getenv("DEV_USER_NAME", "Local Developer")
    app_base_url: str = os.getenv("APP_BASE_URL", "").rstrip("/")
    google_client_id: str = os.getenv("GOOGLE_CLIENT_ID", "")
    google_client_secret: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    allowed_emails: str = os.getenv("ALLOWED_EMAILS", "")
    session_secret_key: str = os.getenv("SESSION_SECRET_KEY", "")
    session_expire_days: int = int(os.getenv("SESSION_EXPIRE_DAYS", "30"))

    # Data Encryption at Rest
    encryption_key: str = os.getenv("OBRIGADO_ENCRYPTION_KEY", "")

    # Paths
    base_dir: Path = BASE_DIR
    data_dir: Path = DATA_DIR
    uploads_dir: Path = UPLOADS_DIR
    db_path: Path = DB_PATH

settings = Settings()
