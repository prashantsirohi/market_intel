from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

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
Analyze the corporate filing text and extract structured financial information.
Return ONLY valid JSON matching this schema:
{
  "primary_category": "management_change|results|capex_expansion|dividend|buyback|rights_issue|regulatory|merger|other",
  "secondary_categories": [],
  "sentiment": "positive|negative|neutral",
  "sentiment_score": -1.0 to 1.0,
  "importance_score": 0.0 to 10.0,
  "revenue_cr": null or number,
  "pat_cr": null or number,
  "eps": null or number,
  "revenue_yoy_pct": null or number,
  "pat_yoy_pct": null or number,
  "capex_amount_cr": null or number,
  "order_value_cr": null or number,
  "dividend_per_share": null or number,
  "buyback_size_cr": null or number,
  "one_line_summary": "max 120 chars",
  "key_highlights": ["3-5 bullet points"],
  "management_guidance": null or string,
  "risk_flags": [],
  "period_label": "Q1 FY25" or null
}"""

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

    def _parse_response(self, raw: str, fallback_title: str) -> InsightPayload:
        try:
            json_str = raw.strip()
            if json_str.startswith("```"):
                json_str = json_str.split("```")[1]
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
                period_label=data.get("period_label"),
                model_used=self.model,
            )
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse LLM response: {e}")
            return InsightPayload(
                one_line_summary=fallback_title[:120],
                model_used=self.model,
            )
