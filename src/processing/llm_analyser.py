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
    revenue_qoq_pct: float | None = None
    pat_qoq_pct: float | None = None
    ebitda_cr: float | None = None
    ebitda_yoy_pct: float | None = None
    ebitda_qoq_pct: float | None = None
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
            "revenue_qoq_pct": self.revenue_qoq_pct,
            "pat_qoq_pct": self.pat_qoq_pct,
            "ebitda_cr": self.ebitda_cr,
            "ebitda_yoy_pct": self.ebitda_yoy_pct,
            "ebitda_qoq_pct": self.ebitda_qoq_pct,
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
        
        response = self._call_llm(prompt)
        payload = self._parse_response(response, filing_title)
        return payload

    def _build_prompt(self, title: str, symbol: str, category: str | None, text: str) -> tuple[str, str]:
        system_prompt = (
            "You are a financial analyst specializing in Indian listed companies (NSE/BSE). "
            "Analyze the corporate filing text and extract structured financial information. "
            "Your response MUST be a single valid JSON object with no text before or after it. "
            "Do NOT use markdown code fences. Do NOT add explanations."
        )

        filtered_text = filter_high_value_pages(text, category or "general", max_chars=16000)

        user_prompt = (
            f"Filing: {title}\n"
            f"Symbol: {symbol}\n"
            f"Category: {category or 'N/A'}\n\n"
            f"Extracted Text (smart page filter):\n{filtered_text}\n\n"
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
            '  "revenue_qoq_pct": null,\n'
            '  "pat_qoq_pct": null,\n'
            '  "ebitda_cr": null,\n'
            '  "ebitda_yoy_pct": null,\n'
            '  "ebitda_qoq_pct": null,\n'
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
            revenue_qoq_pct=data.get("revenue_qoq_pct"),
            pat_qoq_pct=data.get("pat_qoq_pct"),
            ebitda_cr=data.get("ebitda_cr"),
            ebitda_yoy_pct=data.get("ebitda_yoy_pct"),
            ebitda_qoq_pct=data.get("ebitda_qoq_pct"),
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


import re
from datetime import timezone
from processing.taxonomy import IGNORE_CATEGORIES, PDF_LLM_CATEGORIES


def filter_high_value_pages(text: str, category: str, max_chars: int = 12000) -> str:
    page_splitter = re.compile(r"--- PAGE BREAK \[Page (\d+)\] ---")
    parts = page_splitter.split(text)
    
    if len(parts) < 3:
        return text[:max_chars]
        
    pages = []
    if parts[0].strip():
        pages.append((0, parts[0]))
        
    for i in range(1, len(parts), 2):
        try:
            page_num = int(parts[i])
        except ValueError:
            page_num = i // 2 + 1
        page_text = parts[i+1] if i+1 < len(parts) else ""
        pages.append((page_num, page_text))
        
    if not pages:
        return text[:max_chars]
        
    scored_pages = []
    fin_keywords = ["₹", "rs.", "crore", "lakh", "revenue", "profit", "loss", "pat", "ebitda", "income", "sales", "consolidated", "standalone"]
    cat_keywords_map = {
        "results": ["financial results", "statement", "quarter ended", "particulars", "audited", "unaudited", "revenue from operations", "net profit"],
        "management_change": ["resignation", "appointment", "appointed", "resigned", "ceo", "cfo", "md", "director", "managing director", "chief financial officer", "chief executive officer"],
        "regulatory_legal": ["sebi", "nclt", "penalty", "gst", "demand", "show cause", "litigation", "order", "regulation"],
        "buyback": ["buyback", "tender", "repurchase", "shares", "promoter"],
        "major_order_win": ["order win", "received order", "contract", "awarded", "loa", "letter of award", "work order", "purchase order"],
        "capex_expansion": ["capex", "capacity", "expansion", "new plant", "manufacturing", "facility", "project"],
        "fundraise": ["raise", "qip", "issue", "allotment", "preferential", "ncd", "debenture", "warrants"],
        "mna_partnership": ["acquisition", "merger", "partnership", "mou", "agreement", "joint venture", "jv"],
    }
    cat_kws = cat_keywords_map.get(category, [])
    
    for page_num, page_text in pages:
        lower_text = page_text.lower()
        score = 0.0
        for kw in fin_keywords:
            if kw in lower_text:
                score += 1.0
        for kw in cat_kws:
            if kw in lower_text:
                score += 3.0
        num_digits = sum(c.isdigit() for c in page_text)
        total_chars = len(page_text)
        if total_chars > 0:
            digit_ratio = num_digits / total_chars
            score += digit_ratio * 10.0
        scored_pages.append((page_num, page_text, score))
        
    selected_pages = []
    current_len = 0
    
    first_page_num, first_page_text, _ = scored_pages[0]
    selected_pages.append((first_page_num, first_page_text))
    current_len += len(first_page_text)
    
    remaining_pages = scored_pages[1:]
    remaining_pages.sort(key=lambda x: x[2], reverse=True)
    
    for page_num, page_text, score in remaining_pages:
        if current_len + len(page_text) > max_chars:
            if len(selected_pages) < 2 and current_len < max_chars:
                slice_len = max_chars - current_len
                selected_pages.append((page_num, page_text[:slice_len]))
            break
        selected_pages.append((page_num, page_text))
        current_len += len(page_text)
        
    selected_pages.sort(key=lambda x: x[0])
    output = []
    for page_num, page_text in selected_pages:
        output.append(f"--- PAGE BREAK [Page {page_num}] ---\n{page_text}")
    return "\n".join(output)


def enrich_event_with_llm(db: Any, raw_event_id: int, analyser: Optional[LlmAnalyser] = None) -> dict | None:
    with db.get_connection(read_only=True) as conn:
        row = conn.execute(
            """
            SELECT
                r.raw_event_id,
                re.resolved_event_id,
                r.symbol,
                r.company_name,
                r.title,
                r.description,
                r.link,
                r.attachment_url,
                re.primary_category,
                re.event_tier,
                re.alert_level,
                re.importance_score,
                re.trust_score,
                re.novelty_score,
                re.risk_flags_json,
                fd.document_id,
                fd.extracted_text,
                li.insight_id
            FROM resolved_event re
            JOIN raw_event r ON r.raw_event_id = re.raw_event_id
            LEFT JOIN filing_document fd ON fd.raw_event_id = r.raw_event_id
            LEFT JOIN llm_insight li ON li.raw_event_id = r.raw_event_id
            WHERE r.raw_event_id = ?
            """,
            [raw_event_id],
        ).fetchone()
        if not row:
            return None
        cols = [item[0] for item in conn.description]
        row_dict = dict(zip(cols, row))

    insight = build_insight(row_dict, analyser=analyser)
    if insight is not None:
        db.llm_insight_repo().upsert(raw_event_id, insight)
    return insight


def build_insight(row: dict[str, Any], *, analyser: LlmAnalyser | None) -> dict[str, Any] | None:
    from processing.taxonomy import IGNORE_CATEGORIES, PDF_LLM_CATEGORIES
    from datetime import timezone
    category = str(row.get("primary_category") or "general")
    if category in IGNORE_CATEGORIES:
        return None
    title = str(row.get("title") or "").strip()
    description = str(row.get("description") or "").strip()
    text = str(row.get("extracted_text") or description or title)
    should_call_llm = (
        analyser is not None
        and category in PDF_LLM_CATEGORIES
        and len(text.strip()) >= 50
    )

    payload = None
    if should_call_llm:
        try:
            payload = analyser.analyse(
                extracted_text=text,
                filing_title=title,
                symbol=str(row.get("symbol") or ""),
                nse_category=category,
            )
        except Exception as exc:
            logger.warning(
                "LLM analysis failed for event %s (symbol: %s): %s. Falling back to deterministic analysis.",
                row.get("raw_event_id"), row.get("symbol"), exc
            )
            should_call_llm = False

    if should_call_llm and payload is not None:
        data = payload.to_dict()
        summary = data.get("one_line_summary") or title[:160]
        key_facts = data.get("key_highlights") or []
        risk_flags = data.get("risk_flags") or _parse_json_list(row.get("risk_flags_json"))
        what_happened = data.get("what_happened") or summary
        money_value_cr = data.get("money_value_cr") or _first_present(
            data,
            "capex_amount_cr",
            "order_value_cr",
            "buyback_size_cr",
        )
        market_cap_pct = data.get("market_cap_pct")
        time_horizon = data.get("time_horizon") or data.get("impact_horizon") or _impact_horizon(category)
        affected_segment = data.get("affected_segment")
        impact_direction = data.get("impact_direction") or data.get("sentiment") or "neutral"
        changes = {
            "earnings": bool(data.get("changes_earnings")),
            "balance_sheet": bool(data.get("changes_balance_sheet")),
            "ownership": bool(data.get("changes_ownership")),
            "sentiment": bool(data.get("changes_sentiment")),
        }
        provider = "openrouter"
        model_used = payload.model_used or analyser.model
        prompt_tokens = int(data.get("prompt_tokens") or 0)
        completion_tokens = int(data.get("completion_tokens") or 0)
    else:
        summary = _deterministic_summary(title=title, description=description, category=category)
        key_facts = [item for item in [title[:180], description[:220]] if item]
        risk_flags = _parse_json_list(row.get("risk_flags_json"))
        what_happened = summary
        money_value_cr = None
        market_cap_pct = None
        time_horizon = _impact_horizon(category)
        affected_segment = None
        impact_direction = _deterministic_direction(category)
        changes = _deterministic_change_flags(category)
        provider = "deterministic"
        model_used = "deterministic-event-summary"
        prompt_tokens = 0
        completion_tokens = 0

    insight_json = {
        "summary": summary,
        "key_facts": key_facts[:6],
        "sentiment": impact_direction if impact_direction in {"positive", "negative", "neutral"} else "neutral",
        "sentiment_label": impact_direction if impact_direction in {"positive", "negative", "neutral"} else "neutral",
        "risk_flags": risk_flags[:6],
        "what_happened": what_happened,
        "money_value_cr": money_value_cr,
        "market_cap_pct": market_cap_pct,
        "time_horizon": time_horizon,
        "impact_horizon": time_horizon,
        "affected_segment": affected_segment,
        "impact_direction": impact_direction,
        "changes_earnings": changes["earnings"],
        "changes_balance_sheet": changes["balance_sheet"],
        "changes_ownership": changes["ownership"],
        "changes_sentiment": changes["sentiment"],
        "period_label": data.get("period_label") if should_call_llm else None,
        "financials": {
            key: value
            for key, value in {
                "money_value_cr": money_value_cr,
                "market_cap_pct": market_cap_pct,
                "revenue_cr": data.get("revenue_cr") if should_call_llm else None,
                "pat_cr": data.get("pat_cr") if should_call_llm else None,
                "eps": data.get("eps") if should_call_llm else None,
                "revenue_yoy_pct": data.get("revenue_yoy_pct") if should_call_llm else None,
                "pat_yoy_pct": data.get("pat_yoy_pct") if should_call_llm else None,
                "revenue_qoq_pct": data.get("revenue_qoq_pct") if should_call_llm else None,
                "pat_qoq_pct": data.get("pat_qoq_pct") if should_call_llm else None,
                "ebitda_cr": data.get("ebitda_cr") if should_call_llm else None,
                "ebitda_yoy_pct": data.get("ebitda_yoy_pct") if should_call_llm else None,
                "ebitda_qoq_pct": data.get("ebitda_qoq_pct") if should_call_llm else None,
                "period_label": data.get("period_label") if should_call_llm else None,
            }.items()
            if value is not None
        },
        "source_ids": {
            "raw_event_id": row.get("raw_event_id"),
            "resolved_event_id": row.get("resolved_event_id"),
            "document_id": row.get("document_id"),
        },
        "category": category,
        "alert_level": row.get("alert_level"),
        "importance_score": row.get("importance_score"),
        "trust_score": row.get("trust_score"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return {
        "document_id": row.get("document_id"),
        "model_used": model_used,
        "provider": provider,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "insight_json": insight_json,
        **insight_json,
    }


def _deterministic_summary(*, title: str, description: str, category: str) -> str:
    base = title or description or "Corporate event"
    return f"{category}: {base[:180]}"


def _impact_horizon(category: str) -> str:
    if category in {"results", "board_meeting", "dividend"}:
        return "near_term"
    if category in {"capex_expansion", "mna_partnership", "fundraise", "major_order_win"}:
        return "medium_term"
    if category in {"regulatory_legal", "management_change", "promoter_activity"}:
        return "monitor"
    return "unknown"


def _deterministic_direction(category: str) -> str:
    if category in {"regulatory_legal", "rating_downgrade", "insider_sell"}:
        return "negative"
    if category in {"capex_expansion", "mna_partnership", "fundraise", "major_order_win", "buyback", "rating_upgrade", "insider_buy"}:
        return "positive"
    return "neutral"


def _deterministic_change_flags(category: str) -> dict[str, bool]:
    return {
        "earnings": category in {"results", "major_order_win", "capex_expansion"},
        "balance_sheet": category in {"fundraise", "buyback", "capex_expansion"},
        "ownership": category in {"sast_filing", "promoter_activity", "insider_buy", "insider_sell"},
        "sentiment": category in {"regulatory_legal", "management_change", "rating_upgrade", "rating_downgrade", "major_order_win"},
    }


def _first_present(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if data.get(key) is not None:
            return data.get(key)
    return None


def _parse_json_list(value: Any) -> list[str]:
    if not value:
        return []
    try:
        loaded = json.loads(value)
    except (TypeError, ValueError):
        return []
    if isinstance(loaded, list):
        return [str(item) for item in loaded if item]
    return []
