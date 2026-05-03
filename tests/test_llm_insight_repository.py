from __future__ import annotations

import json


def test_llm_insight_upsert_links_resolved_event_and_document(seeded_db):
    with seeded_db.get_connection() as conn:
        raw_id = conn.execute("SELECT raw_event_id FROM raw_event WHERE event_hash = 'hash-reliance-001'").fetchone()[0]
        conn.execute(
            """
            INSERT INTO filing_document(raw_event_id, source_url, document_id)
            VALUES (?, 'https://example.com/doc.pdf', 999)
            """,
            [raw_id],
        )
    insight_id = seeded_db.llm_insight_repo().upsert(
        raw_id,
        {
            "document_id": 999,
            "model_used": "deterministic-event-summary",
            "provider": "deterministic",
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "summary": "Capex summary",
            "source_ids": {"raw_event_id": raw_id},
        },
    )
    with seeded_db.get_connection(read_only=True) as conn:
        resolved = conn.execute("SELECT insight_id FROM resolved_event WHERE raw_event_id = ?", [raw_id]).fetchone()[0]
        doc_json = conn.execute("SELECT llm_insight_json FROM filing_document WHERE document_id = 999").fetchone()[0]
    assert resolved == insight_id
    assert json.loads(doc_json)["summary"] == "Capex summary"


def test_llm_insight_upsert_keeps_one_current_row(seeded_db):
    with seeded_db.get_connection() as conn:
        raw_id = conn.execute("SELECT raw_event_id FROM raw_event WHERE event_hash = 'hash-reliance-001'").fetchone()[0]
    repo = seeded_db.llm_insight_repo()
    repo.upsert(raw_id, {"model_used": "m1", "provider": "deterministic", "summary": "first"})
    repo.upsert(raw_id, {"model_used": "m2", "provider": "deterministic", "summary": "second"})
    with seeded_db.get_connection(read_only=True) as conn:
        count, model = conn.execute(
            "SELECT COUNT(*), MAX(model_used) FROM llm_insight WHERE raw_event_id = ?",
            [raw_id],
        ).fetchone()
    assert count == 1
    assert model == "m2"
