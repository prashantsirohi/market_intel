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
        system_prompt = (
            "You are a financial analyst specializing in Indian listed companies (NSE/BSE). "
            "Analyze the corporate filing text and extract structured financial information. "
            "Your response MUST be a single valid JSON object with no text before or after it. "
            "Do NOT use markdown code fences. Do NOT add explanations."
        )

        user_prompt = (
            f"Filing: {title}\n"
            f"Symbol: {symbol}\n"
            f"Category: {category or 'N/A'}\n\n"
            f"Extracted Text (first 4000 chars):\n{text[:4000]}\n\n"
            "Respond with ONLY a JSON object matching this schema:\n"
            "{\n"
            '  "primary_category": "results"|"dividend"|"buyback"|"capex_expansion"|"management_change"|"rights_issue"|"merger"|"regulatory"|"other",\n'
            '  "secondary_categories": [],\n'
            '  "sentiment": "positive"|"negative"|"neutral",\n'
            '  "sentiment_score": 0.0,\n'
            '  "importance_score": 5.0,\n'
            '  "revenue_cr": null,\n'
            '  "pat_cr": null,\n'
            '  "eps": null,\n'
            '  "revenue_yoy_pct": null,\n'
            '  "pat_yoy_pct": null,\n'
            '  "capex_amount_cr": null,\n'
            '  "order_value_cr": null,\n'
            '  "dividend_per_share": null,\n'
            '  "buyback_size_cr": null,\n'
            '  "one_line_summary": "one sentence summary",\n'
            '  "key_highlights": ["fact1", "fact2"],\n'
            '  "management_guidance": null,\n'
            '  "risk_flags": [],\n'
            '  "period_label": null\n'
            "}\n"
            "Return ONLY the JSON object. No other text."
        )

        return system_prompt, user_prompt

    def _call_llm(self, prompt: tuple[str, str]) -> str:
        import requests

        system, user = prompt

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/prashantsirohi/market_intel",
            "X-Title": "Market Intel",
        }

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": self.max_tokens,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
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

        # Try JSON parsing first
        json_str = raw.strip()
        if json_str.startswith("```"):
            parts = json_str.split("```")
            json_str = parts[1] if len(parts) > 1 else parts[0]
            if json_str.startswith("json"):
                json_str = json_str[4:]
        json_str = json_str.strip()

        # Extract JSON block
        if json_str.startswith("{"):
            data = self._extract_json(json_str)
            if data is not None:
                return self._data_to_payload(data, fallback_title)

        # Extract JSON from mixed text
        start = json_str.find("{")
        end = json_str.rfind("}")
        if start != -1 and end != -1 and end > start:
            data = self._extract_json(json_str[start:end+1])
            if data is not None:
                return self._data_to_payload(data, fallback_title)

        # Fallback: parse as plain text
        return self._text_to_payload(raw, fallback_title)

    def _extract_json(self, json_str: str) -> dict | None:
        """Try to parse JSON, returning None on failure."""
        json_str = "".join(c for c in json_str if ord(c) >= 32 or c in "\n\r\t")
        try:
            data = json.loads(json_str)
            if isinstance(data, dict) and "primary_category" in data:
                return data
        except json.JSONDecodeError:
            pass

        # Try to find a valid JSON object by trimming trailing text
        for i in range(len(json_str), 0, -1):
            if json_str[i-1] == "}":
                candidate = json_str[:i]
                try:
                    data = json.loads(candidate)
                    if isinstance(data, dict) and "primary_category" in data:
                        return data
                except json.JSONDecodeError:
                    continue

        return None

    def _data_to_payload(self, data: dict, fallback_title: str) -> InsightPayload:
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

    def _text_to_payload(self, raw: str, fallback_title: str) -> InsightPayload:
        """Parse plain-text LLM response as fallback."""
        lines = [l.strip() for l in raw.splitlines() if l.strip()]
        summary = ""
        highlights = []
        sentiment = "neutral"

        for line in lines:
            lower = line.lower()
            if line.startswith('"') and line.endswith('"'):
                line = line[1:-1]
            if any(kw in lower for kw in ["summary:", "one line:", "conclusion:"]):
                summary = line.split(":", 1)[-1].strip()
            elif any(kw in lower for kw in ["highlight", "key fact", "bullet", "finding"]):
                highlights.append(line.split(":", 1)[-1].strip() if ":" in line else line)
            elif "positive" in lower and "sentiment" in lower:
                sentiment = "positive"
            elif "negative" in lower and "sentiment" in lower:
                sentiment = "negative"

        if not summary:
            for line in lines:
                clean = line.strip('"').strip()
                if len(clean) > 20 and not clean.startswith("[") and not clean.startswith("{"):
                    summary = clean
                    break

        if not highlights:
            highlights = [l.strip('"').strip() for l in lines if len(l.strip('"').strip()) > 15 and ":" in l][:5]

        return InsightPayload(
            primary_category="other",
            sentiment=sentiment,
            importance_score=5.0,
            one_line_summary=summary[:200] if summary else fallback_title[:120],
            key_highlights=highlights[:5],
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
