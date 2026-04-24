from __future__ import annotations

import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from .data_provider import resolve_provider as resolve_market_provider
from .fundamental_provider import LiveFundamentalProvider

from ..config import UNSUPPORTED_ETF_CODES_FILE


def load_unsupported_etf_codes() -> set[str]:
    path = Path(UNSUPPORTED_ETF_CODES_FILE)
    if not path.exists() or not path.is_file():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    if not isinstance(payload, list):
        return set()
    return {str(item).strip() for item in payload if str(item).strip()}


def effective_unsupported_etf_codes(all_codes: list[str] | set[str]) -> set[str]:
    universe = {str(code).strip() for code in all_codes if str(code).strip()}
    raw = load_unsupported_etf_codes()
    if not universe or not raw:
        return raw & universe if universe else raw

    effective = raw & universe
    remaining = universe - effective
    minimum_visible = max(20, int(len(universe) * 0.05))
    if len(remaining) < minimum_visible:
        return set()
    return effective


def save_unsupported_etf_codes(codes: set[str]) -> None:
    path = Path(UNSUPPORTED_ETF_CODES_FILE)
    path.write_text(
        json.dumps(sorted(codes), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def mark_etf_unsupported(etf_code: str) -> None:
    codes = load_unsupported_etf_codes()
    codes.add(str(etf_code).strip())
    save_unsupported_etf_codes(codes)


def unmark_etf_unsupported(etf_code: str) -> None:
    codes = load_unsupported_etf_codes()
    code = str(etf_code).strip()
    if code not in codes:
        return
    codes.remove(code)
    save_unsupported_etf_codes(codes)


def screen_full_dataset_support(etf_codes: list[str], max_workers: int = 8) -> dict[str, list[str]]:
    supported: list[str] = []
    unsupported: list[str] = []

    def validate(code: str) -> tuple[str, bool]:
        try:
            quotes = resolve_market_provider("auto").fetch_quotes(code, days=40)
            if not quotes:
                return code, False
            _, constituents = LiveFundamentalProvider().fetch_constituents(code, max_items=8)
            if not constituents:
                return code, False
            return code, True
        except Exception:
            return code, False

    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as executor:
        future_map = {executor.submit(validate, code): code for code in etf_codes}
        for future in as_completed(future_map):
            code, ok = future.result()
            if ok:
                supported.append(code)
            else:
                unsupported.append(code)

    return {
        "supported": sorted(supported),
        "unsupported": sorted(unsupported),
    }
