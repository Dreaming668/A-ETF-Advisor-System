import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.database import init_db
from backend.app.bootstrap import bootstrap_database


def main() -> None:
    init_db()
    bootstrap_database()
    print("Database initialized with ETF catalog and base users.")


if __name__ == "__main__":
    main()

