from __future__ import annotations

from sqlalchemy import select

from .catalog import ETF_CATALOG
from .database import session_scope
from .models import ETFMaster, User
from .services.etf_universe_provider import EastmoneyETFUniverseProvider


def bootstrap_database() -> None:
    with session_scope() as session:
        user_exists = session.scalar(select(User).where(User.id == "demo-user"))
        if not user_exists:
            session.add(User(id="demo-user", username="demo", display_name="演示用户"))

        existing = {
            item.code: item
            for item in session.scalars(select(ETFMaster))
        }

        if len(existing) < 1200:
            try:
                for item in EastmoneyETFUniverseProvider().fetch_all():
                    model = existing.get(item.code)
                    if model:
                        model.name = item.name
                        model.category = item.category
                        model.theme = item.theme
                        model.benchmark = item.benchmark
                        model.risk_level = item.risk_level
                        model.description = item.description
                        continue

                    model = ETFMaster(
                        code=item.code,
                        name=item.name,
                        category=item.category,
                        theme=item.theme,
                        benchmark=item.benchmark,
                        risk_level=item.risk_level,
                        description=item.description,
                    )
                    session.add(model)
                    existing[item.code] = model
            except Exception:
                pass

        for item in ETF_CATALOG:
            model = existing.get(item["code"])
            if model:
                model.name = item["name"]
                model.category = item["category"]
                model.theme = item["theme"]
                model.benchmark = item["benchmark"]
                model.risk_level = item["risk_level"]
                model.description = item["description"]
                continue

            model = ETFMaster(
                code=item["code"],
                name=item["name"],
                category=item["category"],
                theme=item["theme"],
                benchmark=item["benchmark"],
                risk_level=item["risk_level"],
                description=item["description"],
            )
            session.add(model)
            existing[item["code"]] = model
