from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # ── OpenAI ──
    OPENAI_API_KEY: str = Field(default="")
    OPENAI_MODEL: str = Field(default="gpt-4o-mini")

    # ── WhatsApp Gateway (WAHA) ──
    WAHA_API_URL: str = Field(default="http://localhost:32768")
    WAHA_API_KEY: str = Field(default="")
    WAHA_SESSION: str = Field(default="Pace")
    WAHA_WEBHOOK_SECRET: str = Field(default="pace_webhook_secret_default")

    # ── Supabase ──
    SUPABASE_URL: str = Field(default="")
    SUPABASE_KEY: str = Field(default="")
    SUPABASE_SERVICE_KEY: Optional[str] = Field(default=None)
    SUPABASE_TABLE: str = Field(default="pace_orders")
    SUPABASE_MENU_TABLE: str = Field(default="MenuPace")

    # ── Redis ──
    REDIS_URL: str = Field(default="redis://localhost:6379/0")

    # ── Access Control ──
    ALLOWED_NUMBERS_ONLY: bool = Field(default=False)
    ALLOWED_NUMBERS: str = Field(default="")

    # ── Restaurant Configuration ──
    RESTAURANT_NAME: str = Field(default="Pace Restaurant")
    RESTAURANT_CITY: str = Field(default="Dera Ismail Khan")
    RESTAURANT_ADDRESS: str = Field(default="East Circular Road, Topan Wala Chowk, Dera Ismail Khan")
    RESTAURANT_PHONE: str = Field(default="0966-710000")
    RESTAURANT_MOBILE: str = Field(default="0332-2716555")
    ADMIN_WHATSAPP: str = Field(default="923306874242")
    ADMIN_2_WHATSAPP: str = Field(default="923306874242")
    KITCHEN_WHATSAPP: str = Field(default="923306874242")
    ADMIN_GROUP_JID: str = Field(default="120363430258815799@g.us")
    MINIMUM_DELIVERY_ORDER: float = Field(default=300.0)

    # ── Menu Images ──
    MENU_IMAGE_1: str = Field(default="https://i.ibb.co/35JBh92c/m1.jpg")
    MENU_IMAGE_2: str = Field(default="https://i.ibb.co/fddn2Myn/m2.jpg")

    # ── App Server ──
    VPS_IP: str = Field(default="72.61.151.29")
    APP_HOST: str = Field(default="0.0.0.0")
    APP_PORT: int = Field(default=4433)
    DASHBOARD_PORT: int = Field(default=4434)
    DEBUG: bool = Field(default=False)
    ORDER_CONFIRM_TIMEOUT_MIN: int = Field(default=10)

    # ── Observability & Logging ──
    LOG_LEVEL: str = Field(default="INFO")
    SENTRY_DSN: Optional[str] = Field(default=None)

    # ── Optional Groq ──
    GROQ_API_KEY: Optional[str] = Field(default=None)


settings = Settings()
