import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.database import session_scope
from backend.app.services.news_sync_service import NewsSyncService
from backend.app.services.sync_service import SyncService


DEFAULT_CODES = ["510300", "510050", "159915", "512100", "515880"]


def main() -> None:
    codes = sys.argv[1:] or DEFAULT_CODES
    with session_scope() as session:
        sync_service = SyncService(session)
        news_service = NewsSyncService(session)
        for code in codes:
            dataset_result = sync_service.refresh_etf_dataset(code, preferred_provider="auto", days=120, max_constituents=10)
            news_result = news_service.refresh_news(code, preferred_provider="auto", limit=6, summarize_with="rules")
            print(
                f"{code}: market={dataset_result['quotes']['provider']}, constituents={dataset_result['fundamentals']['inserted_constituents']}, factor={dataset_result['factors']['composite_score']}, news={news_result['inserted_news']}"
            )


if __name__ == "__main__":
    main()

