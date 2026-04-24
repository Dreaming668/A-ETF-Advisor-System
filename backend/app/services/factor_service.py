from __future__ import annotations

import math
from statistics import mean, pstdev

from ..models import ETFConstituent, ETFQuote


class LiveFactorEngine:
    def build(self, quotes: list[ETFQuote], constituents: list[ETFConstituent]) -> dict:
        if not quotes:
            raise ValueError("Cannot build alpha factors without quotes")

        closes = [item.close_price for item in quotes]
        volumes = [item.volume for item in quotes]
        turnovers = [item.turnover for item in quotes]
        returns = [item.pct_change / 100 for item in quotes[-60:] if item.pct_change is not None]
        latest_date = quotes[-1].trade_date

        momentum_score = self._momentum_score(closes)
        volatility_score = self._volatility_score(returns)
        liquidity_score = self._liquidity_score(turnovers, volumes)
        money_flow_score = self._money_flow_score(closes, volumes)
        valuation_score = self._valuation_score(constituents)
        industry_rotation_score = self._industry_rotation_score(constituents)
        composite = (
            momentum_score * 0.24
            + volatility_score * 0.14
            + liquidity_score * 0.17
            + money_flow_score * 0.16
            + valuation_score * 0.16
            + industry_rotation_score * 0.13
        )
        return {
            "as_of": latest_date,
            "momentum": round(momentum_score, 2),
            "volatility": round(volatility_score, 2),
            "liquidity": round(liquidity_score, 2),
            "money_flow": round(money_flow_score, 2),
            "valuation": round(valuation_score, 2),
            "industry_rotation": round(industry_rotation_score, 2),
            "composite_score": round(composite, 2),
        }

    def _momentum_score(self, closes: list[float]) -> float:
        ret_20 = self._window_return(closes, 20)
        ret_60 = self._window_return(closes, 60)
        ret_120 = self._window_return(closes, 120)
        blended = ret_20 * 0.45 + ret_60 * 0.35 + ret_120 * 0.20
        return _scale(blended, floor=-0.18, ceiling=0.32)

    def _volatility_score(self, returns: list[float]) -> float:
        annualized = pstdev(returns) * math.sqrt(252) if len(returns) > 1 else 0.0
        return _scale(annualized, floor=0.08, ceiling=0.42)

    def _liquidity_score(self, turnovers: list[float], volumes: list[float]) -> float:
        if not turnovers:
            return 0.0
        avg_turnover = mean(turnovers[-20:]) if len(turnovers) >= 20 else mean(turnovers)
        avg_volume = mean(volumes[-20:]) if len(volumes) >= 20 else mean(volumes)
        turnover_component = _scale(math.log10(max(avg_turnover, 1.0)), floor=6.5, ceiling=9.8)
        volume_component = _scale(math.log10(max(avg_volume, 1.0)), floor=5.5, ceiling=8.6)
        return turnover_component * 0.7 + volume_component * 0.3

    def _money_flow_score(self, closes: list[float], volumes: list[float]) -> float:
        if len(closes) < 2 or len(volumes) < 2:
            return 50.0
        obv = 0.0
        obv_series: list[float] = []
        for previous, current, volume in zip(closes[:-1], closes[1:], volumes[1:]):
            if current > previous:
                obv += volume
            elif current < previous:
                obv -= volume
            obv_series.append(obv)
        if len(obv_series) < 5:
            return 50.0
        recent = obv_series[-20:] if len(obv_series) >= 20 else obv_series
        slope = (recent[-1] - recent[0]) / max(abs(recent[0]), 1.0)
        positive_days = sum(1 for previous, current in zip(closes[-21:-1], closes[-20:]) if current > previous)
        breadth = positive_days / max(min(len(closes) - 1, 20), 1)
        return _clamp(_scale(slope, floor=-1.2, ceiling=1.2) * 0.65 + breadth * 100 * 0.35)

    def _valuation_score(self, constituents: list[ETFConstituent]) -> float:
        if not constituents:
            return 50.0
        avg_pe = _weighted_average(*((item.pe, item.weight) for item in constituents))
        avg_pb = _weighted_average(*((item.pb, item.weight) for item in constituents))
        avg_roe = _weighted_average(*((item.roe, item.weight) for item in constituents))
        pe_score = 100 - _scale(avg_pe, floor=8, ceiling=55)
        pb_score = 100 - _scale(avg_pb, floor=0.8, ceiling=8)
        roe_score = _scale(avg_roe, floor=4, ceiling=28)
        return _clamp(pe_score * 0.4 + pb_score * 0.25 + roe_score * 0.35)

    def _industry_rotation_score(self, constituents: list[ETFConstituent]) -> float:
        if not constituents:
            return 50.0
        avg_revenue = _weighted_average(*((item.revenue_growth, item.weight) for item in constituents))
        avg_profit = _weighted_average(*((item.profit_growth, item.weight) for item in constituents))
        sector_weights: dict[str, float] = {}
        total_weight = sum(item.weight for item in constituents) or 1.0
        for item in constituents:
            sector_weights[item.sector] = sector_weights.get(item.sector, 0.0) + item.weight
        concentration = max(sector_weights.values()) / total_weight if sector_weights else 1.0
        breadth_score = _scale(len(sector_weights), floor=1, ceiling=6)
        concentration_score = 100 - _scale(concentration, floor=0.15, ceiling=0.75)
        growth_score = _scale(avg_revenue * 0.45 + avg_profit * 0.55, floor=-20, ceiling=45)
        return _clamp(growth_score * 0.5 + breadth_score * 0.2 + concentration_score * 0.3)

    @staticmethod
    def _window_return(closes: list[float], window: int) -> float:
        if len(closes) <= 1:
            return 0.0
        if len(closes) <= window:
            return closes[-1] / closes[0] - 1
        return closes[-1] / closes[-window] - 1



def _scale(value: float, floor: float, ceiling: float) -> float:
    if ceiling <= floor:
        return 50.0
    normalized = (value - floor) / (ceiling - floor)
    return _clamp(normalized * 100)



def _clamp(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    return max(lower, min(upper, value))



def _weighted_average(*pairs: tuple[float, float]) -> float:
    total_weight = sum(weight for _, weight in pairs) or 1.0
    return sum(value * weight for value, weight in pairs) / total_weight

