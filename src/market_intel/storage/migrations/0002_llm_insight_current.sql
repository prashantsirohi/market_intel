DELETE FROM llm_insight
WHERE insight_id NOT IN (
    SELECT MAX(insight_id)
    FROM llm_insight
    GROUP BY raw_event_id
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_llm_insight_raw_event_unique
ON llm_insight(raw_event_id);

UPDATE resolved_event
SET insight_id = latest.insight_id
FROM (
    SELECT raw_event_id, MAX(insight_id) AS insight_id
    FROM llm_insight
    GROUP BY raw_event_id
) latest
WHERE resolved_event.raw_event_id = latest.raw_event_id;
