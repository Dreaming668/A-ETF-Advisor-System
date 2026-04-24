from pathlib import Path

from .env_loader import load_env_file


BASE_DIR = Path(__file__).resolve().parents[2]
load_env_file(BASE_DIR / '.env')
INSTANCE_DIR = BASE_DIR / 'backend' / 'instance'
DATA_DIR = BASE_DIR / 'data'
REPORT_DIR = DATA_DIR / 'reports'
UNSUPPORTED_ETF_CODES_FILE = DATA_DIR / 'unsupported_etf_codes.json'

INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)


class Config:
    SECRET_KEY = 'etf-advisor-demo-secret'
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{(INSTANCE_DIR / 'advisor.db').as_posix()}"
