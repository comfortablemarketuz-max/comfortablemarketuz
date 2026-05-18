import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://user:password@localhost:5432/qulay_market")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://yourdomain.com/scanner")
WEBAPP_HOST = os.getenv("WEBAPP_HOST", "0.0.0.0")
WEBAPP_PORT = int(os.getenv("WEBAPP_PORT", "8000"))

OWNER_IDS = [int(x) for x in os.getenv("OWNER_IDS", "").split(",") if x.strip()]
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

LOW_STOCK_THRESHOLD = int(os.getenv("LOW_STOCK_THRESHOLD", "5"))
MIN_ORDER_VERIFY_AMOUNT = int(os.getenv("MIN_ORDER_VERIFY_AMOUNT", "50000"))
MIN_PICKUP_MINUTES = int(os.getenv("MIN_PICKUP_MINUTES", "30"))

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")