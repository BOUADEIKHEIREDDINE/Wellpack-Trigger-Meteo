from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

DATA_DIR = BASE_DIR / "data"
CACHE_FILE = DATA_DIR / "cache" / "cache.json"
CONDITIONS_FILE = DATA_DIR / "input" / "Conditions.xlsx"

TEMPLATES_DIR = BASE_DIR / "frontend" / "templates"

