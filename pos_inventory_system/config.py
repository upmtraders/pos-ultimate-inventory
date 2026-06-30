from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DATABASE_DIR = BASE_DIR / "database"
DATA_DIR = BASE_DIR / "data"
DATABASE_PATH = DATA_DIR / "pos_inventory.sqlite3"
