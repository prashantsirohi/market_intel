# Market Intel - Technical Design Document

## 1. Overview

**Project Name**: Market Intel - NSE Corporate Filings Intelligence System  
**Purpose**: Standalone market intelligence monitoring for NSE (National Stock Exchange of India) corporate filings announcements  
**Tech Stack**: Python, DuckDB, Requests

---

## 2. File Structure

```
src/market_intel/
├── __init__.py                 # Package exports: settings
├── __version__ = "0.1.0"
├── settings.py               # Configuration dataclass
├── requirements.txt          # Dependencies
│
├── alerts/
│   ├── __init__.py
│   ├── rules.py            # Alert level decisions
│   └── telegram.py         # TelegramAlert client
│
├── collectors/
│   ├── __init__.py
│   ├── nse_rss.py         # NSE RSS feed fetcher
│   └── corporate_filings.py # NSE API collector
│
├── jobs/
│   ├── collect.py          # Legacy entry point
│   └── run_collect.py      # PRIMARY ENTRY POINT
│
├── processing/
│   ├── __init__.py
│   ├── deduper.py         # Event hash generation
│   ├── entity_resolver.py # Symbol/company resolution
│   └── trust.py           # Trust score computation
│
├── services/
│   ├── __init__.py
│   ├── alert_service.py      # Alert routing
│   ├── event_analysis_service.py # Event classification
│   ├── event_ingest_service.py  # RSS item ingestion
│   ├── event_processor.py      # Legacy processor
│   ├── analysis.py            # Legacy analysis
│   ├── alert.py               # Legacy alerts
│   ├── ingest.py              # Legacy ingest
│   └── telegram_alerts.py    # Legacy telegram
│
├── storage/
│   ├── __init__.py
│   ├── db.py                  # Database class
│   ├── repositories.py        # All data access
│   └── schema.sql            # DuckDB schema
│
└── cli/
    ├── __init__.py
    └── main.py               # CLI entry
```

---

## 3. Module Details

### 3.1 Configuration Module

**File**: `settings.py`

```python
@dataclass
class Settings:
    db_path: str = "./data/market_intel.duckdb"
    data_dir: str = "./data"
    telegram_bot_token: str | None = os.environ.get("TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str | None = os.environ.get("TELEGRAM_CHAT_ID")
    alerts_enabled: bool = True
    critical_immediate: bool = True
    batch_interval_minutes: int = 15
    
    @property
    def telegram_configured(self) -> bool
```

**Export**: `settings = Settings()` (singleton instance)

---

### 3.2 Alert Rules Module

**File**: `alerts/rules.py`

```python
CRITICAL_CATEGORIES = {
    "management_change", "regulatory_legal", "promoter_pledge",
    "buyback", "major_order_win", "capex_expansion"
}

IMPORTANT_CATEGORIES = {
    "board_meeting", "results", "dividend", "rights_issue", "fundraise"
}

def decide_alert_level(
    *,
    primary_category: str | None,
    importance_score: float,
    trust_score: float,
    is_official: bool
) -> str:
    # Returns: "critical" | "important" | "info"
```

**Logic**:
- If category in CRITICAL_CATEGORIES AND trust >= 80 → `critical`
- If importance >= 8.5 AND trust >= 85 → `critical`
- If category in IMPORTANT_CATEGORIES AND trust >= 60 → `important`
- If importance >= 7.0 AND trust >= 60 → `important`
- Otherwise → `info`

---

### 3.3 Telegram Module

**File**: `alerts/telegram.py`

```python
class TelegramAlert:
    def __init__(self, token: str, chat_id: str)
    def send(self, message: str) -> int
        # Sends message via Telegram Bot API
        # Returns HTTP status code (200)
```

---

### 3.4 RSS Collector Module

**File**: `collectors/nse_rss.py`

```
RSS_URL = "https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml"
WARMUP_URLS = [...]
DEFAULT_HEADERS = {...}
```

**Classes**:
- `RssItem(title, link, description, pub_date, guid, raw)` - Dataclass
- `NseRssClient` - Main collector
  - `warmup()` - Warm up requests to establish cookies
  - `fetch_raw_xml()` - Fetch RSS XML
  - `parse_items(xml_text)` - Parse XML to RssItem list
  - `fetch_all()` - Main fetch method with retry logic

**Throttling**: `min_request_gap_sec = 1.5` between requests

---

### 3.5 Processing Modules

#### 3.5.1 Deduper (`processing/deduper.py`)

```python
def normalize_text(text: str | None) -> str:
    # Lowercase, remove special chars, collapse whitespace

def build_event_hash(
    source, symbol, title, event_date,
    attachment_url=None, external_id=None
) -> str:
    # SHA256 hash of: source|symbol|normalized_title|date|url|id
```

#### 3.5.2 Trust Score (`processing/trust.py`)

```python
def compute_trust_score(source: str, source_type: str) -> float:
    # nse/bse → 95.0
    # official_company → 85.0
    # news → 70.0
    # aggregator → 50.0
    # social → 25.0
    # default → 40.0

def is_official_source(source, source_type, source_event_type=None) -> bool:
    return source in {nse, bse} or kind in {official_company, official}
```

#### 3.5.3 Entity Resolver (`processing/entity_resolver.py`)

```python
class EntityResolver:
    def __init__(self, tracked_entities: list[dict])
    def resolve(self, symbol: str | None, title: str | None) -> str | None:
        # Canonicalize symbol, search aliases in title
        # Returns canonical symbol or None
```

---

### 3.6 Service Modules

#### 3.6.1 Event Ingest Service (`services/event_ingest_service.py`)

```python
class EventIngestService:
    def __init__(self, raw_repo, analysis_service)
    def process_rss_item(self, item: dict) -> dict:
        # 1. Check for duplicate via hash
        # 2. Insert raw_event if new
        # 3. Run analysis service
        # 4. Return status: {new|duplicate|error}
```

#### 3.6.2 Event Analysis Service (`services/event_analysis_service.py`)

```python
class EventAnalysisService:
    def __init__(self, raw_repo, resolved_repo, entity_resolver)
    def process_raw_event(self, raw_event: dict, raw_event_id: int) -> dict:
        # 1. Resolve symbol
        # 2. Compute trust score
        # 3. Classify category
        # 4. Compute sentiment
        # 5. Compute importance
        # 6. Decide alert level
        # 7. Upsert resolved_event
        # 8. Mark raw_event as processed
```

**Helper Functions**:
```python
def classify_category(raw_event) -> str:
    # management_change, regulatory_legal, buyback, etc.

def classify_sentiment(raw_event) -> tuple[str, float]:
    # positive/neutral/negative with score

def compute_importance(raw_event, category) -> float:
    # 8.5 for critical categories
    # 7.2 for important
    # 5.0 default
```

#### 3.6.3 Alert Service (`services/alert_service.py`)

```python
class AlertService:
    def __init__(self, alert_repo, telegram_client, dry_run=False)
    
    def route(self, resolved_event, channel="telegram"):
        # critical → send immediately
        # important/info → batch
    
    def flush_batched(self, channel="telegram"):
        # Send batched important alerts
    
    def send_if_needed(self, resolved_event, channel="telegram"):
        # Check if already sent, create pending, send, mark sent/failed
```

---

### 3.7 Storage Modules

#### 3.7.1 Database (`storage/db.py`)

```python
class Database:
    def __init__(self, db_path="./data/market_intel.duckdb", fresh=False)
    def _init_db(self) -> None:
        # Execute schema.sql
    @contextmanager
    def get_connection(self, read_only=False):
        # Yield DuckDB connection
    def tracked_entity_repo(self) -> TrackedEntityRepository
    def raw_event_repo(self) -> RawEventRepository
    def resolved_event_repo(self) -> ResolvedEventRepository
    def alert_log_repo(self) -> AlertLogRepository
```

#### 3.7.2 Repositories (`storage/repositories.py`)

**Data Classes**:
- `TrackedEntity`
- `RawEvent`
- `ResolvedEvent`
- `AlertLog`
- `UpsertRawEventResult`

**Repositories**:

| Repository | Key Methods |
|------------|------------|
| `TrackedEntityRepository` | `upsert()`, `get_by_symbol()`, `list_active()` |
| `RawEventRepository` | `upsert_event()`, `get_by_hash()`, `list_unprocessed()`, `mark_processed()` |
| `ResolvedEventRepository` | `upsert()`, `get_by_raw_id()`, `list_by_alert_level()` |
| `AlertLogRepository` | `create()`, `mark_sent()`, `mark_failed()`, `is_duplicate()` |

---

### 3.8 Job Entry Point

**File**: `jobs/run_collect.py`

```python
def main() -> None:
    # 1. Parse args (db-path, dry-run, telegram config)
    # 2. Initialize Database
    # 3. Create repositories
    # 4. Create EntityResolver
    # 5. Create services (ingest, analysis, alert)
    # 6. Create NseRssClient
    # 7. Fetch RSS items
    # 8. For each item:
    #    - Process via EventIngestService
    #    - Route via AlertService
    # 9. Flush batched alerts
    # 10. Print stats
```

---

## 4. Control Flow

### 4.1 Main Collection Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    run_collect.py                            │
├─────────────────────────────────────────────────────────────┤
│  1. Parse CLI args (db-path, --dry-run-alerts, etc.)           │
│  2. Initialize Database(db_path, fresh=True)                │
│  3. Create repositories                                     │
│     ├── TrackedEntityRepository                              │
│     ├── RawEventRepository                                 │
│     ├── ResolvedEventRepository                            │
│     └── AlertLogRepository                                 │
│  4. Create services                                       │
│     ├── EntityResolver(list_active)                          │
│     ├── EventAnalysisService                              │
│     ├── EventIngestService                              │
│     └── AlertService (with Telegram if configured)        │
│  5. NseRssClient().fetch_all()                           │
│     └── Warmup → Fetch XML → Parse Items                     │
└───────────────────────┬─────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│              For Each RSS Item                          │
├─────────────────────────────────────────────────────────────┤
│  EventIngestService.process_rss_item(item)              │
│  ├── build_event_hash()                                 │
│  ├── get_by_hash() → check duplicate                    │
│  ├── upsert_event() → insert new RAW_EVENT           │
│  └── if new: call analysis_service                   │
└───────────────────────┬─────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│          EventAnalysisService.process_raw_event         │
├─────────────────────────────────────────────────────────────┤
│  1. Resolve symbol via EntityResolver                 │
│  2. compute_trust_score()                           │
│  3. is_official_source()                            │
│  4. classify_category() → primary_category          │
│  5. classify_sentiment() → sentiment_label/score  │
│  6. compute_importance() → importance_score      │
│  7. decide_alert_level() → alert_level            │
│  8. ResolvedEventRepository.upsert()             │
│  9. mark_processed()                               │
└───────────────────────┬─────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│             AlertService.route(resolved_event)         │
├─────────────────────────────────────────────────────────────┤
���  if alert_level == "critical":                         │
│      send_if_needed() → Telegram send                │
│  else:                                             │
│      batch for later                                │
└───────────────────────┬─────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                  Final Stats                             │
├─────────────────────────────────────────────────────────────┤
│  {fetched_count, new_count, duplicate_count,        │
│   resolved_count, critical_count, important_count,  │
│   failed_count}                                      │
└─────────────────────────────────────────────────────────────┘
```

---

## 5. Database Schema

### Tables

| Table | Primary Key | Key Fields |
|-------|------------|-----------|
| `tracked_entity` | entity_id | symbol (UNIQUE) |
| `raw_event` | raw_event_id | event_hash (UNIQUE) |
| `resolved_event` | resolved_event_id | raw_event_id (UNIQUE) |
| `filing_document` | document_id | source_url (UNIQUE) |
| `alert_log` | alert_id | alert_key (UNIQUE) |

### Indexes

```sql
idx_tracked_entity_active ON tracked_entity(is_active)
idx_raw_event_hash ON raw_event(event_hash)
idx_raw_event_symbol_date ON raw_event(symbol, event_date)
idx_raw_event_status ON raw_event(processing_status)
idx_resolved_event_alert_level ON resolved_event(alert_level)
idx_resolved_event_status ON resolved_event(status)
idx_alert_log_event_id ON alert_log(resolved_event_id)
```

---

## 6. API Reference

### Command Line

```bash
python -m market_intel.jobs.run_collect [OPTIONS]

Options:
  --db-path PATH           DuckDB path (default: ./data/market_intel.duckdb)
  --dry-run-alerts         Skip sending alerts
  --telegram-bot-token TOKEN
  --telegram-chat-id TOKEN
```

### Environment Variables

| Variable | Description |
|----------|-------------|
| `MARKET_INTEL_DB_PATH` | Database path |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token |
| `TELEGRAM_CHAT_ID` | Telegram chat ID |
| `MARKET_INTEL_ALERTS_ENABLED` | Enable alerts (1/0) |

---

## 7. Key Functions Summary

| Module | Function | Purpose |
|--------|----------|---------|
| `alerts/rules.py` | `decide_alert_level()` | Determine alert priority |
| `alerts/telegram.py` | `TelegramAlert.send()` | Send Telegram message |
| `processing/deduper.py` | `build_event_hash()` | SHA256 for deduplication |
| `processing/trust.py` | `compute_trust_score()` | Source reliability score |
| `processing/entity_resolver.py` | `EntityResolver.resolve()` | Symbol canonicalization |
| `services/event_analysis_service.py` | `process_raw_event()` | Full event analysis |
| `services/event_ingest_service.py` | `process_rss_item()` | Ingest with dedup |
| `services/alert_service.py` | `route()` | Alert routing |
| `storage/repositories.py` | `upsert_event()` | Insert/update events |

---

*Document Version: 0.1.0*  
*Last Updated: 2026-04-27*