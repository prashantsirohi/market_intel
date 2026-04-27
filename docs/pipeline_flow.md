# NSE Corporate Filings Pipeline

## RSS Ingestion → Classification → Alert Flow

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                           NSE RSS FEED COLLECTION                                  │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│  STEP 1: NseRssClient.fetch_all()                                                 │
│  ────────────────────────────────────────────────────────────                         │
│  • Fetch from nseindia.com/rss/home.aspx?subType=corp                             │
│  • Parse XML → RssItem[] (title, description, link, pub_date, guid)              │
│  • Output: 320 items fetched                                                 │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│  STEP 2: Raw Event Storage (DuckDB)                                             │
│  ────────────────────────────────────────────────────────────                     │
│  INSERT INTO raw_events (title, link, pub_date, description, guid, ...)              │
│  • Dedupe by guid                                                            │
│  • Store: title, link, pub_date, description, category, importance, sentiment   │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│  STEP 3: classify_category() - EVENT TYPE EXTRACTION                            │
│  ───────────────────────────────────────────────────────────��                     │
│  Input: raw_event = {title, description}                                       │
│                                                                            │
│  1. Extract NSE event type:                                                 │
│     desc.split("|")[-1].strip()  →  "SUBJECT: Declaration of NAV"                │
│                                                                            │
│  2. Match against NSE event types:                                          │
│                                                                            │
│     ┌─────────────────────────────────────────────────────────────────────┐   │
│     │ PRIORITY 1: Most Common (225 items)                           │   │
│     │ "declaration of nav" + ("Mutual Fund" OR "ETF" in title)  │   │
│     │ → mutual_fund_nav (LOW - skip alerting)                │   │
│     └─────────────────────────────────────────────────────────────────────┘   │
│     ┌─────────────────────────────────────────────────────────────────────┐   │
│     │ PRIORITY 2: Board Meetings (17 items)                       │   │
│     │ "board meeting" + "intimation"                        │   │ → board_meeting_intimation
│     │ "board meeting" + "outcome"                          │   │ → board_meeting_outcome
│     │ "board meeting" (default)                           │   │ → board_meeting
│     └─────────────────────────────────────────────────────────────────────┘   │
│     ┌─────────────────────────────────────────────────────────────────────┐   │
│     │ PRIORITY 3: Management Changes (6 items)           │   │
│     │ "change in directors" / "change in kmp" /          │   │
│     │ "cessation" / "demise"                             │   │ → management_change
│     └─────────────────────────────────────────────────────────────────────┘   │
│     ┌─────────────────────────────────────────────────────────────────────┐   │
│     │ PRIORITY 4: Corporate Actions                       │   │
│     │ "buyback" / "repurchase"                          │   │ → buyback
│     │ "dividend" / "record date"                       │   │ → dividend
│     │ "rights issue" / "qip"                          │   │ → fundraise
│     │ "esop" / "esos" / "esps"                       │   │ → esop_allotment
│     │ "bagging" / "award" / "loa"                     │   │ → major_order_win
│     │ "result" / "quarterly"                         │   │ → results
│     └──────────────────────────────────────────────────────────────���──────┘   │
│     ┌─────────────────────────────────────────────────────────────────────┐   │
│     │ PRIORITY 5: Regulatory (3 items)                       │   │
│     │ "sebi" / "takeover" / "regulation"               │   │ → regulatory
│     │ "deviation" / "variation"                      │   │ → deviation_statement
│     └─────────────────────────────────────────────────────────────────────┘   │
│     ┌─────────────────────────────────────────────────────────────────────┐   │
│     │ DEFAULT: Other (22 items)                           │   │
│     │ "press release"                             │   │ → press_release
│     │ "newspaper publication"                     │   │ → newspaper_publication
│     │ "shareholders meeting"                     │   │ → shareholders_meeting
│     │ "analyst" / "investor meet"                │   │ → investor_meet
│     │ (anything else)                           │   │ → general
│     └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│  STEP 4: compute_importance() - IMPORTANCE SCORING                               │
│  ────────────────────────────────────────────────────────────                     │
│  Input: category (from classify_category)                                      │
│                                                                            │
│  importance_score = {                                                        │
│      "management_change":    8.5,  // HIGH                                    │
│      "major_order_win":     8.5,  // HIGH                                    │
│      "buyback":            8.5,  // HIGH                                    │
│      "dividend":          7.2,  // IMPORTANT                               │
│      "results":           7.2,  // IMPORTANT                               │
│      "board_meeting_*":    7.2,  // IMPORTANT                               │
│      "fundraise":         7.2,  // IMPORTANT                               │
│      "mutual_fund_nav":   5.0,  // LOW - skip alerts                        │
│      "general":           5.0,  // LOW                                     │
│  }                                                                          │
└─────────────────────────────────────────────────────��─��─────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│  STEP 5: classify_sentiment() - SENTIMENT ANALYSIS                            │
│  ────────────────────────────────────────────────────────────                     │
│  Input: raw_event description                                                │
│                                                                            │
│  positive_keywords = ["buyback", "order win", "expansion", "dividend",           │
│                      "rating upgrade", "bonus"]                               │
│  negative_keywords = ["penalty", "pledge", "downgrade", "default",           │
│                      "resignation", "tax demand", "loss"]                   │
│                                                                            │
│  Output: ("positive", +0.5) | ("negative", -0.5) | ("neutral", 0.0)          │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌───────────────────────────────────────────────────────────────────────────��─────────────────┐
│  STEP 6: decide_alert_level() - ALERT ROUTING                                    │
│  ────────────────────────────────────────────────────────────                     │
│  Input: category, importance_score, trust_score, is_official                    │
│                                                                            │
│  ┌─────────────────────────────────────────────────────────────────┐       │
│  │ CRITICAL (immediate Telegram):                                   │       │
│  │   category in CRITICAL_CATEGORIES AND trust >= 80                   │       │
│  │   OR importance >= 8.5 AND trust >= 85                          │       │
│  └─────────────────────────────────────────────────────────────────┘       │
│  ┌─────────────────────────────────────────────────────────────────┐       │
│  │ IMPORTANT (batched Telegram, 15min):                          │       │
│  │   category in IMPORTANT_CATEGORIES AND trust >= 60                 │       │
│  │   OR importance >= 7.0 AND trust >= 60                         │       │
│  └─────────────────────────────────────────────────────────────────┘       │
│  ┌─────────────────────────────────────────────────────────────────┐       │
│  │ INFO (skipped, for reference only):                               │       │
│  │   everything else                                             │       │
│  └─────────────────────────────────────────────────────────────────┘       │
│                                                                            │
│  CRITICAL_CATEGORIES = {management_change, regulatory, buyback,             │
│                        major_order_win, capex_expansion}                     │
│  IMPORTANT_CATEGORIES = {board_meeting, results, dividend, fundraise}          │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│  STEP 7: Alert Delivery                                                    │
│  ────────────────────────────────────────────────────────────                     │
│  CRITICAL → Telegram immediately                                         │
│  IMPORTANT → Telegram batched (15 min)                                    │
│  INFO → Skip (logged only)                                                │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

## Summary Statistics

| Stage | Count | Notes |
|-------|-------|-------|
| RSS Fetched | 320 | From NSE |
| Stored | 320 | DuckDB |
| mutual_fund_nav | 225 | Skip - low value |
| board_meeting_* | 17 | Important |
| management_change | 6 | HIGH - 8.5 |
| major_order_win | 3 | HIGH - 8.5 |
| dividend | 1 | Important - 7.2 |
| regulatory | 3 | Important |
| general/other | 22 | Review later |

## Key Insight
Most NSE filings (225/320 = 70%) are **Mutual Fund NAV declarations** - not useful for stock trading. These are filtered out early.