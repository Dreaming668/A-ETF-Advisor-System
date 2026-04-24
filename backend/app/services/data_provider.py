from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from .http_client import build_session


@dataclass
class ProviderProbe:
    name: str
    installed: bool
    usable: bool
    detail: str


@dataclass
class QuoteRecord:
    trade_date: date
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float
    turnover: float


def _etf_symbol(etf_code: str) -> str:
    market = "sh" if etf_code.startswith(("5", "6")) else "sz"
    return f"{market}{etf_code}"


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return default


class TencentMarketDataProvider:
    name = "tencent"

    def __init__(self):
        self.session = build_session()

    def fetch_quotes(self, etf_code: str, days: int = 120) -> list[QuoteRecord]:
        symbol = _etf_symbol(etf_code)
        response = self.session.get(
            "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
            params={"param": f"{symbol},day,,,{max(days + 80, 240)},"},
            timeout=18,
        )
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("data", {}).get(symbol, {}).get("day") or payload.get("data", {}).get(symbol, {}).get("qfqday") or []
        records: list[QuoteRecord] = []
        for row in rows[-days:]:
            open_price = _to_float(row[1])
            close_price = _to_float(row[2])
            high_price = _to_float(row[3])
            low_price = _to_float(row[4])
            volume = _to_float(row[5])
            avg_price = (open_price + close_price + high_price + low_price) / 4 if high_price and low_price else close_price
            turnover = round(avg_price * volume, 2)
            records.append(
                QuoteRecord(
                    trade_date=date.fromisoformat(row[0]),
                    open_price=round(open_price, 4),
                    high_price=round(high_price, 4),
                    low_price=round(low_price, 4),
                    close_price=round(close_price, 4),
                    volume=round(volume, 2),
                    turnover=turnover,
                )
            )
        return records


class SinaMarketDataProvider:
    name = "sina"

    def __init__(self):
        self.session = build_session()

    def fetch_quotes(self, etf_code: str, days: int = 120) -> list[QuoteRecord]:
        symbol = _etf_symbol(etf_code)
        response = self.session.get(
            "https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_data=/CN_MarketDataService.getKLineData",
            params={"symbol": symbol, "scale": "240", "ma": "no", "datalen": str(max(days, 120))},
            timeout=18,
        )
        response.raise_for_status()
        match = re.search(r"=\((\[.*\])\)", response.text, re.S)
        if not match:
            return []
        rows = json.loads(match.group(1))
        records: list[QuoteRecord] = []
        for row in rows[-days:]:
            open_price = _to_float(row.get("open"))
            close_price = _to_float(row.get("close"))
            high_price = _to_float(row.get("high"))
            low_price = _to_float(row.get("low"))
            volume = _to_float(row.get("volume"))
            avg_price = (open_price + close_price + high_price + low_price) / 4 if high_price and low_price else close_price
            turnover = round(avg_price * volume, 2)
            records.append(
                QuoteRecord(
                    trade_date=date.fromisoformat(row["day"]),
                    open_price=round(open_price, 4),
                    high_price=round(high_price, 4),
                    low_price=round(low_price, 4),
                    close_price=round(close_price, 4),
                    volume=round(volume, 2),
                    turnover=turnover,
                )
            )
        return records


def provider_status() -> dict[str, Any]:
    return {
        "preferred": "tencent",
        "providers": [
            {"name": "tencent", "installed": True, "usable": True, "detail": "腾讯财经 ETF 历史 K 线接口"},
            {"name": "sina", "installed": True, "usable": True, "detail": "新浪财经 K 线接口"},
        ],
    }


def resolve_provider(preferred: str = "auto"):
    providers = []
    if preferred in {"auto", "tencent"}:
        providers.append(TencentMarketDataProvider())
    if preferred in {"auto", "sina"}:
        providers.append(SinaMarketDataProvider())
    if not providers:
        raise ValueError(f"Unsupported market data provider: {preferred}")
    if preferred != "auto":
        return providers[0]

    class AutoMarketDataProvider:
        name = "auto"

        def fetch_quotes(self, etf_code: str, days: int = 120) -> list[QuoteRecord]:
            errors: list[str] = []
            for provider in providers:
                try:
                    records = provider.fetch_quotes(etf_code, days=days)
                except Exception as exc:
                    errors.append(f"{provider.name}: {exc}")
                    continue
                if records:
                    self.name = provider.name
                    return records
                errors.append(f"{provider.name}: empty")
            raise RuntimeError("; ".join(errors) or "No live market provider returned data")

    return AutoMarketDataProvider()
