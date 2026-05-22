from __future__ import annotations

import json
import pytest
from processing.pdf_extractor import _needs_table_extraction
from processing.llm_analyser import filter_high_value_pages, enrich_event_with_llm
from services.alert_service import AlertService


def test_needs_table_extraction_trigger():
    # Simple comma announcement should not trigger table extraction
    simple_doc = {"pages": [{"text": "Reliance announces resignation of MD, effective today"}]}
    assert not _needs_table_extraction(simple_doc)

    # Financial keywords or symbols should trigger table extraction
    results_doc = {"pages": [{"text": "Standalone results: consolidated particulars and ₹ 150 crore"}]}
    assert _needs_table_extraction(results_doc)


def test_filter_high_value_pages():
    # 3-page document structure:
    # Page 1: Cover page / metadata (should always be retained as first page)
    # Page 2: Noise / unrelated text
    # Page 3: Standalone and Consolidated Financial Results (₹, lakhs, revenue)
    text = (
        "--- PAGE BREAK [Page 1] ---\n"
        "Reliance Industries Limited Corporate Announcement\n"
        "--- PAGE BREAK [Page 2] ---\n"
        "This page contains random meeting minutes and administrative notices with no numbers.\n"
        "--- PAGE BREAK [Page 3] ---\n"
        "Consolidated Financial Results for quarter ended March 31, 2026. Revenue from operations is ₹ 15000 crore. PAT is 5000."
    )
    
    # We filter with a small character limit to force selection of only high-value pages
    filtered = filter_high_value_pages(text, category="results", max_chars=180)
    
    # Page 1 (metadata) and Page 3 (high score page) must be present in the output
    assert "[Page 1]" in filtered
    assert "[Page 3]" in filtered
    # Page 2 (low score noise page) should be ranked lower and excluded due to character budget
    assert "[Page 2]" not in filtered


def test_inline_enrichment_writes_to_db(seeded_db):
    with seeded_db.get_connection() as conn:
        raw_id = conn.execute("SELECT raw_event_id FROM raw_event WHERE event_hash = 'hash-reliance-001'").fetchone()[0]
    
    # Enrich the event using deterministic fallback (analyser=None)
    insight = enrich_event_with_llm(seeded_db, raw_id, analyser=None)
    
    assert insight is not None
    assert insight["provider"] == "deterministic"
    assert "capex_expansion" in insight["summary"]
    
    # Verify it exists in db
    with seeded_db.get_connection(read_only=True) as conn:
        row = conn.execute("SELECT insight_json FROM llm_insight WHERE raw_event_id = ?", [raw_id]).fetchone()
        assert row is not None
        db_insight = json.loads(row[0])
        assert db_insight["summary"] == insight["summary"]


class MockTelegramClient:
    def __init__(self):
        self.sent_messages = []

    def send(self, msg: str):
        self.sent_messages.append(msg)


class MockAlertRepo:
    def __init__(self):
        self.sent_ids = set()
        self.alerts = []

    def already_sent(self, resolved_event_id, channel) -> bool:
        return resolved_event_id in self.sent_ids

    def create_pending(self, resolved_event_id, channel, payload) -> int:
        alert_id = len(self.alerts) + 1
        self.alerts.append({"id": alert_id, "resolved_event_id": resolved_event_id, "payload": payload})
        return alert_id

    def mark_sent(self, alert_id):
        self.sent_ids.add(alert_id)

    def mark_failed(self, alert_id, err):
        pass


def test_alert_service_builds_premium_html(seeded_db):
    with seeded_db.get_connection() as conn:
        raw_id = conn.execute("SELECT raw_event_id FROM raw_event WHERE event_hash = 'hash-reliance-001'").fetchone()[0]
    
    # 1. First test without LLM Insight (should build fallback message)
    alert_repo = MockAlertRepo()
    telegram = MockTelegramClient()
    svc = AlertService(alert_repo, telegram, dry_run=False, db=seeded_db)
    
    resolved_event = {
        "resolved_event_id": 101,
        "raw_event_id": raw_id,
        "symbol": "RELIANCE",
        "primary_category": "capex_expansion",
        "alert_level": "critical",
        "summary_text": "Reliance announces Rs 15000cr capex plan.",
    }
    
    svc.send_if_needed(resolved_event)
    assert len(telegram.sent_messages) == 1
    msg1 = telegram.sent_messages[0]
    assert "🚨 <b>🔴 CRITICAL ALERT</b>" in msg1
    assert "🏢 <b>Symbol:</b> RELIANCE" in msg1
    # Without insight, "Detail" section is shown
    assert "📝 <b>Detail:</b> Reliance announces Rs 15000cr capex plan." in msg1

    # 2. Upsert LLM insight into db
    seeded_db.llm_insight_repo().upsert(raw_id, {
        "summary": "Reliance plans monumental ₹15,000 cr capex for Jamnagar.",
        "key_facts": ["Greenfield expansion", "5000 new jobs created"],
        "sentiment": "positive",
        "risk_flags": ["Execution delays"],
        "model_used": "deterministic-event-summary",
        "provider": "deterministic"
    })
    
    # 3. Test with LLM Insight (should build premium HTML message)
    telegram_with_insight = MockTelegramClient()
    svc_with_insight = AlertService(MockAlertRepo(), telegram_with_insight, dry_run=False, db=seeded_db)
    
    # Use a different resolved_event_id to bypass "already sent" checks
    resolved_event_new = dict(resolved_event)
    resolved_event_new["resolved_event_id"] = 102
    
    svc_with_insight.send_if_needed(resolved_event_new)
    assert len(telegram_with_insight.sent_messages) == 1
    msg2 = telegram_with_insight.sent_messages[0]
    assert "🚨 <b>🔴 CRITICAL ALERT</b>" in msg2
    assert "🏢 <b>Symbol:</b> RELIANCE" in msg2
    assert "⚖️ <b>Sentiment:</b> 🟢 Positive" in msg2
    assert "📝 <b>Summary:</b> Reliance plans monumental ₹15,000 cr capex for Jamnagar." in msg2
    assert "🔑 <b>Key Highlights:</b>" in msg2
    assert "• Greenfield expansion" in msg2
    assert "⚠️ <b>Risk Flags:</b>" in msg2
    assert "• Execution delays" in msg2


def test_alert_service_flush_batched_uses_llm_insight(seeded_db):
    with seeded_db.get_connection() as conn:
        raw_id = conn.execute("SELECT raw_event_id FROM raw_event WHERE event_hash = 'hash-reliance-001'").fetchone()[0]
        
    seeded_db.llm_insight_repo().upsert(raw_id, {
        "summary": "Reliance plans monumental ₹15,000 cr capex for Jamnagar.",
        "sentiment": "positive",
        "model_used": "deterministic-event-summary",
        "provider": "deterministic"
    })

    alert_repo = MockAlertRepo()
    telegram = MockTelegramClient()
    svc = AlertService(alert_repo, telegram, dry_run=False, db=seeded_db)
    
    # Add an event with LLM insight to batched important events
    svc.route({
        "resolved_event_id": 105,
        "raw_event_id": raw_id,
        "symbol": "RELIANCE",
        "primary_category": "capex_expansion",
        "alert_level": "important",
        "summary_text": "Reliance plans capex expansion.",
    })
    
    # Add a normal event without LLM insight
    svc.route({
        "resolved_event_id": 106,
        "raw_event_id": 99999, # non-existent ID
        "symbol": "INFY",
        "primary_category": "dividend",
        "alert_level": "important",
        "summary_text": "Infosys declares dividend.",
    })
    
    svc.flush_batched()
    
    assert len(telegram.sent_messages) == 1
    batch_msg = telegram.sent_messages[0]
    
    assert "📋 <b>IMPORTANT ALERTS SUMMARY</b>" in batch_msg
    # The RELIANCE event should use LLM summary and have green sentiment prefix
    assert "🟢 <b>RELIANCE</b>: Reliance plans monumental ₹15,000 cr capex for Jamnagar." in batch_msg
    # The INFY event should use summary_text and neutral/white sentiment prefix
    assert "⚪ <b>INFY</b>: Infosys declares dividend." in batch_msg


def test_inline_enrichment_handles_llm_exception_fallback(seeded_db):
    with seeded_db.get_connection() as conn:
        raw_id = conn.execute("SELECT raw_event_id FROM raw_event WHERE event_hash = 'hash-reliance-001'").fetchone()[0]

    class ExplodingAnalyser:
        def __init__(self):
            self.model = "exploding-model"
        def analyse(self, *args, **kwargs):
            raise RuntimeError("API Rate Limit exceeded (429)")

    # Run the enrichment, passing the ExplodingAnalyser
    insight = enrich_event_with_llm(seeded_db, raw_id, analyser=ExplodingAnalyser())

    # It must cleanly fall back to deterministic and not crash
    assert insight is not None
    assert insight["provider"] == "deterministic"
    assert insight["model_used"] == "deterministic-event-summary"

