import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
DEFAULT_REWARD_GROUP_ID = int(os.getenv("REWARD_GROUP_ID", "0"))
DB_PATH = os.getenv("DB_PATH", "bot_data.db")

