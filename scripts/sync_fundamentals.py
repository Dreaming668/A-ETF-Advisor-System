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
            result = service.refresh_etf_fundamentals(code, max_items=10)
            factor_result = service.refresh_etf_factors(code)
            print(
                f"{code}: provider={result['provider']}, constituents={result['inserted_constituents']}, report_date={result['report_date']}, factor_score={factor_result['composite_score']}"
            )


if __name__ == "__main__":
    main()
