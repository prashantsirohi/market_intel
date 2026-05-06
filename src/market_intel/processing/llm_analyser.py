from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class InsightPayload:
    primary_category: str = "general"
    secondary_categories: list[str] = None
    sentiment: str = "neutral"
    sentiment_score: float = 0.0
    importance_score: float = 5.0
    
    revenue_cr: float | None = None
    pat_cr: float | None = None
    eps: float | None = None
    revenue_yoy_pct: float | None = None
    pat_yoy_pct: float | None = None
    capex_amount_cr: float | None = None
    order_value_cr: float | None = None
    dividend_per_share: float | None = None
    buyback_size_cr: float | None = None
    
    one_line_summary: str = ""
    key_highlights: list[str] = None
    management_guidance: str | None = None
    risk_flags: list[str] = None

    what_happened: str | None = None
    money_value_cr: float | None = None
    market_cap_pct: float | None = None
    time_horizon: str | None = None
    affected_segment: str | None = None
    impact_direction: str = "neutral"
    changes_earnings: bool = False
    changes_balance_sheet: bool = False
    changes_ownership: bool = False
    changes_sentiment: bool = False
    
    period_label: str | None = None
    model_used: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    analysis_timestamp: datetime = None

    def __post_init__(self):
        if self.secondary_categories is None:
            self.secondary_categories = []
        if self.key_highlights is None:
            self.key_highlights = []
        if self.risk_flags is None:
            self.risk_flags = []
        if self.analysis_timestamp is None:
            self.analysis_timestamp = datetime.now()

    def to_dict(self) -> dict:
        return {
            "primary_category": self.primary_category,
            "secondary_categories": self.secondary_categories,
            "sentiment": self.sentiment,
            "sentiment_score": self.sentiment_score,
            "importance_score": self.importance_score,
            "revenue_cr": self.revenue_cr,
            "pat_cr": self.pat_cr,
            "eps": self.eps,
            "revenue_yoy_pct": self.revenue_yoy_pct,
            "pat_yoy_pct": self.pat_yoy_pct,
            "capex_amount_cr": self.capex_amount_cr,
            "order_value_cr": self.order_value_cr,
            "dividend_per_share": self.dividend_per_share,
            "buyback_size_cr": self.buyback_size_cr,
            "one_line_summary": self.one_line_summary,
            "key_highlights": self.key_highlights,
            "management_guidance": self.management_guidance,
            "risk_flags": self.risk_flags,
            "what_happened": self.what_happened,
            "money_value_cr": self.money_value_cr,
            "market_cap_pct": self.market_cap_pct,
            "time_horizon": self.time_horizon,
            "affected_segment": self.affected_segment,
            "impact_direction": self.impact_direction,
            "changes_earnings": self.changes_earnings,
            "changes_balance_sheet": self.changes_balance_sheet,
            "changes_ownership": self.changes_ownership,
            "changes_sentiment": self.changes_sentiment,
            "period_label": self.period_label,
            "model_used": self.model_used,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "analysis_timestamp": self.analysis_timestamp.isoformat() if self.analysis_timestamp else None,
        }


class LlmAnalyser:
    def __init__(
        self,
        api_key: str,
        model: str = "openai/gpt-4o-mini",
        base_url: str = "https://openrouter.ai/api/v1",
        max_tokens: int = 1024,
        timeout: int = 30,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.max_tokens = max_tokens
        self.timeout = timeout

    def analyse(
        self,
        extracted_text: str,
        filing_title: str,
        symbol: str,
        nse_category: str | None = None,
    ) -> InsightPayload:
        if not extracted_text or len(extracted_text.strip()) < 50:
            logger.warning(f"Extracted text too short for LLM analysis: {len(extracted_text)} chars")
            return InsightPayload(
                one_line_summary=filing_title[:120],
                model_used=self.model,
            )

        prompt = self._build_prompt(filing_title, symbol, nse_category, extracted_text)
        
        try:
            response = self._call_llm(prompt)
            payload = self._parse_response(response, filing_title)
            return payload
        except Exception as e:
            logger.error(f"LLM analysis failed: {e}")
            return InsightPayload(
                one_line_summary=filing_title[:120],
                model_used=self.model,
            )

    def _build_prompt(self, title: str, symbol: str, category: str | None, text: str) -> tuple[str, str]:
        system_prompt = """You are a financial analyst specializing in Indian listed companies (NSE/BSE).
Analyze the corporate filing text and extract structured event information for trading operations.
Return ONLY valid JSON (no markdown, no explanation).

Schema:
{
  "primary_category": "results"|"dividend"|"buyback"|"capex_expansion"|"management_change"|"rights_issue"|"merger"|"regulatory"|"other",
  "secondary_categories": [],
  "sentiment": "positive"|"negative"|"neutral",
  "sentiment_score": 0.0,
  "importance_score": 5.0,
  "revenue_cr": null,
  "pat_cr": null,
  "eps": null,
  "revenue_yoy_pct": null,
  "pat_yoy_pct": null,
  "capex_amount_cr": null,
  "order_value_cr": null,
  "dividend_per_share": null,
  "buyback_size_cr": null,
  "one_line_summary": "",
  "key_highlights": [],
  "management_guidance": null,
  "risk_flags": [],
  "what_happened": "",
  "money_value_cr": null,
  "market_cap_pct": null,
  "time_horizon": "immediate"|"near_term"|"medium_term"|"long_term"|"unknown",
  "affected_segment": null,
  "impact_direction": "positive"|"negative"|"neutral",
  "changes_earnings": false,
  "changes_balance_sheet": false,
  "changes_ownership": false,
  "changes_sentiment": false,
  "period_label": null
}

Return only JSON object, no text before or after."""

        user_prompt = f"""Filing: {title}
Symbol: {symbol}
Category: {category or 'N/A'}

Extracted Text (first 4000 chars):
{text[:4000]}

Return ONLY the JSON, no other text."""

        return system_prompt, user_prompt

    def _call_llm(self, prompt: tuple[str, str]) -> str:
        import requests
        
        system, user = prompt
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": self.max_tokens,
            "temperature": 0.2,
        }
        
        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    def _parse_response(self, raw: str | None, fallback_title: str) -> InsightPayload:
        if not raw:
            logger.warning("Empty LLM response")
            return InsightPayload(
                one_line_summary=fallback_title[:120],
                model_used=self.model,
            )
        
        try:
            json_str = raw.strip()
            if json_str.startswith("```"):
                parts = json_str.split("```")
                json_str = parts[1] if len(parts) > 1 else parts[0]
                if json_str.startswith("json"):
                    json_str = json_str[4:]
            json_str = json_str.strip()
            
            data = json.loads(json_str)
            
            return InsightPayload(
                primary_category=data.get("primary_category", "other"),
                secondary_categories=data.get("secondary_categories", []),
                sentiment=data.get("sentiment", "neutral"),
                sentiment_score=float(data.get("sentiment_score", 0.0)),
                importance_score=float(data.get("importance_score", 5.0)),
                revenue_cr=data.get("revenue_cr"),
                pat_cr=data.get("pat_cr"),
                eps=data.get("eps"),
                revenue_yoy_pct=data.get("revenue_yoy_pct"),
                pat_yoy_pct=data.get("pat_yoy_pct"),
                capex_amount_cr=data.get("capex_amount_cr"),
                order_value_cr=data.get("order_value_cr"),
                dividend_per_share=data.get("dividend_per_share"),
                buyback_size_cr=data.get("buyback_size_cr"),
                one_line_summary=data.get("one_line_summary", fallback_title[:120]),
                key_highlights=data.get("key_highlights", []),
                management_guidance=data.get("management_guidance"),
                risk_flags=data.get("risk_flags", []),
                what_happened=data.get("what_happened"),
                money_value_cr=data.get("money_value_cr"),
                market_cap_pct=data.get("market_cap_pct"),
                time_horizon=data.get("time_horizon"),
                affected_segment=data.get("affected_segment"),
                impact_direction=data.get("impact_direction", data.get("sentiment", "neutral")),
                changes_earnings=bool(data.get("changes_earnings", False)),
                changes_balance_sheet=bool(data.get("changes_balance_sheet", False)),
                changes_ownership=bool(data.get("changes_ownership", False)),
                changes_sentiment=bool(data.get("changes_sentiment", False)),
                period_label=data.get("period_label"),
                model_used=self.model,
            )
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse LLM response: {e}, raw: {raw[:200] if raw else 'None'}")
            return InsightPayload(
                one_line_summary=fallback_title[:120],
                model_used=self.model,
            )


def recalculate_importance(insight: InsightPayload, base_importance: float) -> float:
    score = base_importance

    if insight.pat_yoy_pct:
        if abs(insight.pat_yoy_pct) > 25:
            score += 1.5
        elif abs(insight.pat_yoy_pct) > 10:
            score += 0.5

    if insight.management_guidance:
        score += 0.5

    if insight.risk_flags:
        score += 0.5 * min(len(insight.risk_flags), 3)

    if insight.revenue_yoy_pct:
        if insight.revenue_yoy_pct > 20 or insight.revenue_yoy_pct < -20:
            score += 0.5

    if insight.buyback_size_cr:
        score += 1.0

    return min(score, 10.0)
