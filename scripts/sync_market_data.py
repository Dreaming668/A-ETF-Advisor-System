import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.database import session_scope
from backend.app.services.sync_service import SyncService


DEFAULT_CODES = ["510300", "510050", "159915", "512100", "515880"]


def main() -> None:
    codes = sys.argv[1:] or DEFAULT_CODES
    with session_scope() as session:
        service = SyncService(session)
        for code in codes:
            result = service.refresh_etf_quotes(code, preferred_provider="auto", days=120)
            print(f"{code}: provider={result['provider']}, inserted={result['inserted_quotes']}, latest={result['latest_trade_date']}")


if __name__ == "__main__":
    main()
