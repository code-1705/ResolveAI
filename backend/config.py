import os
from pydantic import BaseModel

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
    
    # Merchant Default Guardrails
    DEFAULT_MIN_PARTIAL_PAYMENT_PCT: float = 30.0  # Min 30% of remaining balance
    DEFAULT_MAX_EXTENSION_DAYS: int = 14          # Max 14 days extension
    DEFAULT_MAX_SPLIT_INSTALLMENTS: int = 3       # Max 3 split payments
    DEFAULT_AUTO_DISCOUNT_WAIVER_PCT: float = 5.0  # Max 5% waiver
    DEFAULT_TONE: str = "professional_empathetic"
    
    # Database Configuration
    DATABASE_PATH: str = os.path.join(os.path.dirname(__file__), "resolve_ai.db")

settings = Settings()
