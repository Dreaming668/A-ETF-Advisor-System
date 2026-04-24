from __future__ import annotations

from sqlalchemy import delete, select

from ..models import ETFConstituent, ETFFactor, ETFQuote
from .data_provider import resolve_provider as resolve_market_provider
from .factor_service import LiveFactorEngine
from .fundamental_provider import LiveFundamentalProvider


class SyncService:
    def __init__(self, session):
        self.session = session

    def refresh_etf_quotes(self, etf_code: str, preferred_provider: str = "auto", days: int = 120) -> dict:
        provider = resolve_market_provider(preferred_provider)
        quotes = provider.fetch_quotes(etf_code, days=days)
        if not quotes:
            raise RuntimeError(f"Live market provider {provider.name} returned no quotes")

        self.session.execute(delete(ETFQuote).where(ETFQuote.etf_code == etf_code))

        previous_close = None
        inserted = 0
        for item in quotes:
            pct_change = 0.0 if previous_close in (None, 0) else round((item.close_price / previous_close - 1) * 100, 2)
            self.session.add(
                ETFQuote(
                    etf_code=etf_code,
                    trade_date=item.trade_date,
                    open_price=item.open_price,
                    high_price=item.high_price,
                    low_price=item.low_price,
                    close_price=item.close_price,
                    volume=item.volume,
                    turnover=item.turnover,
                    pct_change=pct_change,
                )
            )
            previous_close = item.close_price
            inserted += 1

        self.session.flush()
        return {
            "etf_code": etf_code,
            "provider": provider.name,
            "inserted_quotes": inserted,
            "latest_trade_date": quotes[-1].trade_date.isoformat(),
            "latest_close": quotes[-1].close_price,
        }

    def refresh_etf_fundamentals(self, etf_code: str, max_items: int = 10) -> dict:
        provider = LiveFundamentalProvider()
        report_date, constituents = provider.fetch_constituents(etf_code, max_items=max_items)
        self.session.execute(delete(ETFConstituent).where(ETFConstituent.etf_code == etf_code))
        for item in constituents:
            self.session.add(
                ETFConstituent(
                    etf_code=etf_code,
                    stock_code=item.stock_code,
                    stock_name=item.stock_name,
                    weight=item.weight,
                    pe=item.pe,
                    pb=item.pb,
                    roe=item.roe,
                    revenue_growth=item.revenue_growth,
                    profit_growth=item.profit_growth,
                    sector=item.sector,
                )
            )
        self.session.flush()
        return {
            "etf_code": etf_code,
            "provider": provider.name,
            "inserted_constituents": len(constituents),
            "report_date": report_date.isoformat(),
        }

    def refresh_etf_factors(self, etf_code: str) -> dict:
        quotes = list(self.session.scalars(select(ETFQuote).where(ETFQuote.etf_code == etf_code).order_by(ETFQuote.trade_date.asc())))
        constituents = list(self.session.scalars(select(ETFConstituent).where(ETFConstituent.etf_code == etf_code)))
        if not quotes:
            raise RuntimeError(f"Cannot build alpha factors for ETF {etf_code} without live quotes")
        if not constituents:
            raise RuntimeError(f"Cannot build alpha factors for ETF {etf_code} without live constituent fundamentals")
        factor_payload = LiveFactorEngine().build(quotes, constituents)
        self.session.execute(delete(ETFFactor).where(ETFFactor.etf_code == etf_code))
        self.session.add(
            ETFFactor(
                etf_code=etf_code,
                as_of=factor_payload["as_of"],
                momentum=factor_payload["momentum"],
                volatility=factor_payload["volatility"],
                liquidity=factor_payload["liquidity"],
                money_flow=factor_payload["money_flow"],
                valuation=factor_payload["valuation"],
                industry_rotation=factor_payload["industry_rotation"],
                composite_score=factor_payload["composite_score"],
            )
        )
        self.session.flush()
        return {
            "etf_code": etf_code,
            "provider": "live_factor_engine",
            "as_of": factor_payload["as_of"].isoformat(),
            "composite_score": factor_payload["composite_score"],
        }

    def refresh_etf_dataset(self, etf_code: str, preferred_provider: str = "auto", days: int = 120, max_constituents: int = 10) -> dict:
        quote_result = self.refresh_etf_quotes(etf_code, preferred_provider=preferred_provider, days=days)
        fundamental_result = self.refresh_etf_fundamentals(etf_code, max_items=max_constituents)
        factor_result = self.refresh_etf_factors(etf_code)
        return {
            "etf_code": etf_code,
            "quotes": quote_result,
            "fundamentals": fundamental_result,
            "factors": factor_result,
        }
