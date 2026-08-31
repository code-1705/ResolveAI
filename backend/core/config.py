"""
Core Configuration Module
Loads and manages environment variables, secrets, and application-wide settings.
"""

import os
from pydantic import BaseModel
from typing import Optional

# Load .env file automatically if python-dotenv is installed or read manually
env_file_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
if os.path.exists(env_file_path):
    try:
        from dotenv import load_dotenv
        load_dotenv(env_file_path)
    except ImportError:
        # Fallback manual parsing if python-dotenv not installed
        with open(env_file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())

class Settings(BaseModel):
    APP_NAME: str = "Resolve.ai Autonomous Collections Agent"
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")

    # Razorpay Credentials (Default to mock mode if not provided)
    RAZORPAY_KEY_ID: str = os.getenv("RAZORPAY_KEY_ID", "rzp_test_mock12345678")
    RAZORPAY_KEY_SECRET: str = os.getenv("RAZORPAY_KEY_SECRET", "mock_secret_87654321")
    RAZORPAY_WEBHOOK_SECRET: str = os.getenv("RAZORPAY_WEBHOOK_SECRET", "mock_webhook_secret_999")

    # Meta WhatsApp Credentials
    META_WHATSAPP_TOKEN: str = os.getenv("META_WHATSAPP_TOKEN", "mock_meta_token")
    META_WHATSAPP_PHONE_ID: str = os.getenv("META_WHATSAPP_PHONE_ID", "mock_phone_id")
    META_VERIFY_TOKEN: str = os.getenv("META_VERIFY_TOKEN", "resolve_ai_webhook_token_2026")
    META_APP_SECRET: str = os.getenv("META_APP_SECRET", "mock_meta_app_secret_123")

    # LLM API Credentials
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-5.4-nano")

    # Merchant Default Guardrails
    DEFAULT_MIN_PARTIAL_PAYMENT_PCT: float = 30.0  # Min 30% of remaining balance
    DEFAULT_MAX_EXTENSION_DAYS: int = 14          # Max 14 days extension
    DEFAULT_MAX_SPLIT_INSTALLMENTS: int = 3       # Max 3 split payments
    DEFAULT_AUTO_DISCOUNT_WAIVER_PCT: float = 5.0  # Max 5% waiver
    DEFAULT_TONE: str = "professional_empathetic"

    @property
    def is_test_env(self) -> bool:
        import sys
        return bool(os.getenv("PYTEST_CURRENT_TEST")) or "unittest" in sys.argv[0] or any("unittest" in arg for arg in sys.argv)

    @property
    def get_db_url(self) -> Optional[str]:
        return os.getenv("DATABASE_URL")

    @property
    def get_redis_url(self) -> Optional[str]:
        return os.getenv("REDIS_URL")

    DATABASE_URL: Optional[str] = os.getenv("DATABASE_URL")
    REDIS_URL: Optional[str] = os.getenv("REDIS_URL")

    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "https://lcpyyilepfnlmbrwdzcv.supabase.co")
    SUPABASE_SERVICE_KEY: str = os.getenv("SUPABASE_SERVICE_KEY", "")

    # JWT Authentication Configuration
    JWT_SECRET: str = os.getenv("JWT_SECRET", "resolve_ai_jwt_secret_key_2026")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")

settings = Settings()
if settings.is_test_env and not os.getenv("DATABASE_URL"):
    settings.DATABASE_URL = None
    settings.REDIS_URL = None
