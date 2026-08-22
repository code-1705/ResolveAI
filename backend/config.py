import os
from pydantic import BaseModel

# Load .env file automatically if python-dotenv is installed or read manually
env_file_path = os.path.join(os.path.dirname(__file__), "..", ".env")
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
    
    # LLM API Credentials
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    
    # Merchant Default Guardrails
    DEFAULT_MIN_PARTIAL_PAYMENT_PCT: float = 30.0  # Min 30% of remaining balance
    DEFAULT_MAX_EXTENSION_DAYS: int = 14          # Max 14 days extension
    DEFAULT_MAX_SPLIT_INSTALLMENTS: int = 3       # Max 3 split payments
    DEFAULT_AUTO_DISCOUNT_WAIVER_PCT: float = 5.0  # Max 5% waiver
    DEFAULT_TONE: str = "professional_empathetic"
    
    # Database Configuration
    DATABASE_PATH: str = os.path.join(os.path.dirname(__file__), "resolve_ai.db")

settings = Settings()
