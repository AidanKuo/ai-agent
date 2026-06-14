from pathlib import Path

BASE_DIR    = Path(__file__).parent.parent
APPS_PATH   = BASE_DIR / "data" / "applications.json"
LOG_PATH    = BASE_DIR / "logs" / "agent.log"
CONFIG_PATH = BASE_DIR / "config" / "settings.yaml"
