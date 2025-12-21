from pathlib import Path

# Racine du projet
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Dossiers de données
DATA_DIR = BASE_DIR / "data"
CACHE_FILE = DATA_DIR / "cache" / "cache.json"
CONDITIONS_FILE = DATA_DIR / "input" / "Conditions.xlsx"

# Templates frontend
TEMPLATES_DIR = BASE_DIR / "frontend" / "templates"

