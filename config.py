import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-in-production-abc123")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "defects2024")

DATA_DIR = os.environ.get("DATA_DIR", BASE_DIR)

SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(DATA_DIR, "database.db")
SQLALCHEMY_TRACK_MODIFICATIONS = False

UPLOAD_FOLDER = os.path.join(DATA_DIR, "uploads")
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB max upload

TRADES = [
    "Painter",
    "Carpenter",
    "Tiler",
    "Electrician",
    "Plumber",
    "Cabinet Maker",
    "HVAC Technician",
    "Glazier",
    "Stonemason",
    "Laborer",
    "Landscaper",
    "Cleaner",
    "Renderer",
    "Concreter",
    "Roofer",
    "Other",
]

LOCATIONS = (
    [f"Unit {i}" for i in range(1, 26)]
    + ["Driveway", "Garden", "Gatehouse", "Bin Pad", "Outside", "Common Area", "Other"]
)
