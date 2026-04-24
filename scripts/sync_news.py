import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.database import session_scope
from backend.app.services.news_sync_service import NewsSyncService


DEFAULT_CODES = ["510300", "510050", "159915", "512100", "515880"]


def main() -> None:
    codes = sys.argv[1:] or DEFAULT_CODES
    with session_scope() as session:
        service = NewsSyncService(session)
        for code in codes:
            result = service.refresh_news(code, preferred_provider="auto", limit=6, summarize_with="rules")
            print(f"{code}: provider={result['provider']}, inserted_news={result['inserted_news']}")


if __name__ == "__main__":
    main()

