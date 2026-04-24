from __future__ import annotations

from sqlalchemy import delete

from ..models import ETFMaster, ETFNews
from .news_provider import NewsSummaryService, resolve_news_provider


class NewsSyncService:
    def __init__(self, session):
        self.session = session

    def refresh_news(self, etf_code: str, preferred_provider: str = "auto", limit: int = 6, summarize_with: str = "auto") -> dict:
        etf_model = self.session.get(ETFMaster, etf_code)
        if not etf_model:
            raise ValueError(f"ETF not found: {etf_code}")
        etf = {
            "code": etf_model.code,
            "name": etf_model.name,
            "benchmark": etf_model.benchmark,
            "theme": etf_model.theme,
            "category": etf_model.category,
        }
        provider = resolve_news_provider(preferred_provider)
        items = provider.fetch_news(etf, limit=limit)
        if not items:
            raise RuntimeError(f"Live news provider {provider.name} returned no items")

        items = NewsSummaryService().summarize(etf, items, preferred_provider=summarize_with)
        self.session.execute(delete(ETFNews).where(ETFNews.etf_code == etf_code))
        for item in items:
            self.session.add(
                ETFNews(
                    etf_code=etf_code,
                    title=item.title,
                    source=item.source,
                    published_at=item.published_at,
                    sentiment=item.sentiment,
                    summary=item.summary,
                )
            )
        return {
            "etf_code": etf_code,
            "provider": provider.name,
            "inserted_news": len(items),
            "latest_published_at": items[0].published_at.isoformat(timespec="seconds") if items else None,
        }
