from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from bs4 import BeautifulSoup

from .http_client import build_session


@dataclass
class HoldingRecord:
    stock_code: str
    stock_name: str
    weight: float
    holding_shares: float
    holding_value: float
    report_date: date


@dataclass
class ConstituentSnapshot:
    stock_code: str
    stock_name: str
    weight: float
    pe: float
    pb: float
    roe: float
    revenue_growth: float
    profit_growth: float
    sector: str


class LiveFundamentalProvider:
    name = "eastmoney_sina"

    def __init__(self):
        self.session = build_session()

    def fetch_constituents(self, etf_code: str, max_items: int = 10) -> tuple[date, list[ConstituentSnapshot]]:
        holdings = self._fetch_latest_holdings(etf_code, max_items=max_items)
        report_date = holdings[0].report_date
        snapshots: list[ConstituentSnapshot] = []
        errors: list[str] = []
        with ThreadPoolExecutor(max_workers=min(4, max(1, len(holdings)))) as executor:
            future_map = {executor.submit(self._build_constituent_snapshot, item): item for item in holdings}
            for future in as_completed(future_map):
                holding = future_map[future]
                try:
                    result = future.result()
                except Exception as exc:
                    errors.append(f"{holding.stock_code}: {exc}")
                    continue
                if result:
                    snapshots.append(result)
        snapshots.sort(key=lambda item: item.weight, reverse=True)
        minimum_required = max(5, min(8, len(holdings) // 2 or 1))
        if len(snapshots) < minimum_required:
            raise RuntimeError(
                f"No enough live constituent fundamentals for ETF {etf_code}: {len(snapshots)} ok; errors={'; '.join(errors[:3])}"
            )
        return report_date, snapshots

    def fetch_holdings(self, etf_code: str, max_items: int = 10) -> tuple[date, list[HoldingRecord]]:
        holdings = self._fetch_latest_holdings(etf_code, max_items=max_items)
        return holdings[0].report_date, holdings

    def _fetch_latest_holdings(self, etf_code: str, max_items: int) -> list[HoldingRecord]:
        current_year = date.today().year
        years = [str(current_year), str(current_year - 1), str(current_year - 2), str(current_year - 3)]
        errors: list[str] = []
        for year in years:
            try:
                records = self._fetch_holdings_by_year(etf_code, year, max_items=max_items)
            except Exception as exc:
                errors.append(f"{year}: {exc}")
                continue
            if records:
                return records
            errors.append(f"{year}: empty")
        raise RuntimeError("; ".join(errors) or f"Holdings fetch failed for ETF {etf_code}")

    def _fetch_holdings_by_year(self, etf_code: str, year: str, max_items: int) -> list[HoldingRecord]:
        response = self.session.get(
            "https://fundf10.eastmoney.com/FundArchivesDatas.aspx",
            params={"type": "jjcc", "code": etf_code, "topline": str(max(max_items, 20)), "year": year, "month": ""},
            headers={"Referer": f"https://fundf10.eastmoney.com/ccmx_{etf_code}.html"},
            timeout=20,
        )
        response.raise_for_status()
        match = re.search(r'content:"(.*)",arryear', response.text, re.S)
        if not match:
            return []
        content = _decode_archive_html(match.group(1))
        soup = BeautifulSoup(content, "html.parser")
        tables = soup.select("table")
        titles = soup.select("h4.t")
        if not tables:
            return []
        records: list[HoldingRecord] = []
        for index, table in enumerate(tables):
            report_date = self._extract_report_date(titles[index].get_text(" ", strip=True) if index < len(titles) else "")
            for row in table.select("tbody tr"):
                cells = [cell.get_text(" ", strip=True) for cell in row.find_all("td")]
                if len(cells) < 7:
                    continue
                stock_code = cells[1]
                if not stock_code.isdigit():
                    continue
                # Eastmoney fund holding tables currently expose 7 columns.
                # The stable numeric fields remain the last three columns:
                # weight, holding shares, holding value.
                records.append(
                    HoldingRecord(
                        stock_code=stock_code,
                        stock_name=cells[2],
                        weight=_percent_to_float(cells[-3]),
                        holding_shares=_to_float(cells[-2]),
                        holding_value=_to_float(cells[-1]),
                        report_date=report_date,
                    )
                )
            if records:
                break
        return records[:max_items]

    def _build_constituent_snapshot(self, holding: HoldingRecord) -> ConstituentSnapshot | None:
        snapshot = self._fetch_stock_snapshot(holding.stock_code)
        summary = self._fetch_financial_summary(holding.stock_code)
        market_cap = _to_float(snapshot.get("market_cap"))
        net_assets = _to_float(summary.get("net_assets"))
        parent_profit = _to_float(summary.get("parent_net_profit"))
        pe = self._compute_pe(market_cap, parent_profit, summary.get("report_date"))
        pb = self._compute_pb(market_cap, net_assets, _to_float(snapshot.get("price")), _to_float(summary.get("naps")))
        roe = _first_valid(_to_float(snapshot.get("roe"), default=-1), _to_float(summary.get("roe"), default=-1))
        revenue_growth = _first_valid(_to_float(snapshot.get("revenue_growth"), default=-999), _to_float(summary.get("revenue_growth"), default=-999))
        profit_growth = _first_valid(_to_float(snapshot.get("profit_growth"), default=-999), _to_float(summary.get("profit_growth"), default=-999))
        if roe < 0:
            roe = 0.0
        if revenue_growth <= -999:
            revenue_growth = 0.0
        if profit_growth <= -999:
            profit_growth = 0.0
        return ConstituentSnapshot(
            stock_code=holding.stock_code,
            stock_name=holding.stock_name or str(snapshot.get("name") or holding.stock_code),
            weight=holding.weight,
            pe=round(max(pe, 0.0), 2),
            pb=round(max(pb, 0.0), 2),
            roe=round(roe, 2),
            revenue_growth=round(revenue_growth, 2),
            profit_growth=round(profit_growth, 2),
            sector=str(snapshot.get("sector") or "未分类"),
        )

    def _fetch_stock_snapshot(self, stock_code: str) -> dict[str, Any]:
        secid = f"{_market_id(stock_code)}.{stock_code}"
        response = self.session.get(
            "https://push2.eastmoney.com/api/qt/stock/get",
            params={
                "fltt": "2",
                "invt": "2",
                "secid": secid,
                "fields": "f57,f58,f43,f116,f117,f127,f173,f183,f184,f185",
            },
            timeout=15,
        )
        response.raise_for_status()
        data = response.json().get("data") or {}
        return {
            "code": data.get("f57", stock_code),
            "name": data.get("f58", stock_code),
            "price": data.get("f43"),
            "market_cap": data.get("f116") or data.get("f117"),
            "sector": data.get("f127"),
            "roe": data.get("f173"),
            "revenue_growth": data.get("f184"),
            "profit_growth": data.get("f185"),
        }

    def _fetch_financial_summary(self, stock_code: str) -> dict[str, Any]:
        paper_code = f"{'sh' if _market_id(stock_code) == 1 else 'sz'}{stock_code}"
        response = self.session.get(
            "https://quotes.sina.cn/cn/api/openapi.php/CompanyFinanceService.getFinanceReport2022",
            params={"paperCode": paper_code, "source": "gjzb", "type": "0", "page": "1", "num": "100"},
            timeout=18,
        )
        response.raise_for_status()
        payload = response.json().get("result", {}).get("data", {})
        report_dates = payload.get("report_date") or []
        if not report_dates:
            return {}
        latest_key = report_dates[0].get("date_value")
        items = payload.get("report_list", {}).get(latest_key, {}).get("data", [])
        by_field = {item.get("item_field"): item for item in items if item.get("item_field")}
        return {
            "report_date": latest_key,
            "parent_net_profit": _to_float(by_field.get("PARENETP", {}).get("item_value")),
            "net_assets": _to_float(by_field.get("RIGHAGGR", {}).get("item_value")),
            "naps": _to_float(by_field.get("NAPS", {}).get("item_value")),
            "roe": _normalize_percent(by_field.get("ROEWEIGHTED", {}).get("item_value")),
            "revenue_growth": _normalize_growth(by_field.get("BIZTOTINCO", {}).get("item_tongbi")),
            "profit_growth": _normalize_growth(by_field.get("PARENETP", {}).get("item_tongbi")),
        }

    @staticmethod
    def _compute_pe(market_cap: float, parent_profit: float, report_date: str | None) -> float:
        if market_cap <= 0 or parent_profit <= 0:
            return 0.0
        annualized_profit = parent_profit * _annualize_factor(report_date)
        return market_cap / annualized_profit if annualized_profit > 0 else 0.0

    @staticmethod
    def _compute_pb(market_cap: float, net_assets: float, price: float, naps: float) -> float:
        if market_cap > 0 and net_assets > 0:
            return market_cap / net_assets
        if price > 0 and naps > 0:
            return price / naps
        return 0.0

    @staticmethod
    def _extract_report_date(title: str) -> date:
        match = re.search(r"(\d{4}-\d{2}-\d{2})", title)
        if match:
            return datetime.strptime(match.group(1), "%Y-%m-%d").date()
        return date.today()


def _market_id(stock_code: str) -> int:
    return 1 if stock_code.startswith(("5", "6", "9")) else 0


def _decode_archive_html(value: str) -> str:
    decoded = bytes(value, "utf-8").decode("unicode_escape").replace("\\/", "/")
    try:
        repaired = decoded.encode("latin1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        repaired = decoded
    return repaired


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return default


def _percent_to_float(value: str) -> float:
    return _to_float(str(value).replace("%", ""))


def _normalize_growth(value: Any) -> float:
    numeric = _to_float(value, default=0.0)
    return numeric * 100 if abs(numeric) <= 1 else numeric


def _normalize_percent(value: Any) -> float:
    numeric = _to_float(value, default=0.0)
    return numeric * 100 if abs(numeric) <= 1 else numeric


def _annualize_factor(report_date: str | None) -> float:
    if not report_date:
        return 1.0
    suffix = str(report_date)[-4:]
    mapping = {"1231": 1.0, "0930": 4 / 3, "0630": 2.0, "0331": 4.0}
    return mapping.get(suffix, 1.0)


def _first_valid(primary: float, fallback: float) -> float:
    return primary if primary not in {-1, -999} else fallback
