ALTER TABLE resolved_event ADD COLUMN IF NOT EXISTS event_tier VARCHAR;
ALTER TABLE resolved_event ADD COLUMN IF NOT EXISTS ignored_reason VARCHAR;

UPDATE resolved_event
SET event_tier = CASE
    WHEN primary_category IN (
        'management_change',
        'regulatory_legal',
        'major_order_win',
        'capex_expansion',
        'buyback',
        'promoter_activity',
        'demerger',
        'block_deal',
        'sast_filing',
        'rating_downgrade'
    ) THEN 'A'
    WHEN primary_category IN (
        'results',
        'board_meeting',
        'dividend',
        'fundraise',
        'mna_partnership',
        'bulk_deal',
        'insider_buy',
        'insider_sell',
        'rating_upgrade'
    ) THEN 'B'
    WHEN primary_category IN (
        'credit_rating',
        'guidance',
        'clarification',
        'rating_reaffirmed'
    ) THEN 'C'
    WHEN primary_category IN (
        'nav_update',
        'newspaper_publication',
        'investor_meet',
        'agm_notice',
        'compliance_certificate',
        'loss_of_certificate',
        'analyst_call'
    ) THEN 'IGNORE'
    ELSE 'GENERAL'
END
WHERE event_tier IS NULL;

UPDATE resolved_event
SET ignored_reason = 'ignored:' || primary_category
WHERE ignored_reason IS NULL
  AND event_tier = 'IGNORE'
  AND primary_category IS NOT NULL;
