# Market Intel - NSE Corporate Filings Intelligence

Standalone market intelligence monitoring system for NSE (National Stock Exchange of India) corporate filings announcements.

## Features

- **RSS Collection**: Fetches corporate announcements from NSE RSS feed
- **Event Deduplication**: SHA256-based event hashing to detect duplicates
- **Entity Resolution**: Resolves symbols and company names from tracked entities
- **Trust Scoring**: Computes trust scores based on source reliability
- **Category Classification**: Automatic categorization (results, dividend, buyback, etc.)
- **Alert Routing**: Intelligent alert routing with critical/important/info levels
- **Telegram Alerts**: Optional Telegram bot notifications

## Installation

```bash
pip install -r src/market_intel/requirements.txt
```

Requirements:
- `duckdb>=1.0`
- `requests`

## Usage

### Entry Point

```bash
python -m market_intel.jobs.run_collect --db-path ./data/market_intel.duckdb --dry-run-alerts
```

### Options

| Flag | Description | Default |
|------|-------------|---------|
| `--db-path` | DuckDB path | `./data/market_intel.duckdb` |
| `--dry-run-alerts` | Skip sending alerts | `False` |
| `--telegram-bot-token` | Telegram bot token | From env |
| `--telegram-chat-id` | Telegram chat ID | From env |

### Environment Variables

```bash
export MARKET_INTEL_DB_PATH=./data/market_intel.duckdb
export TELEGRAM_BOT_TOKEN=your_bot_token
export TELEGRAM_CHAT_ID=your_chat_id
export MARKET_INTEL_ALERTS_ENABLED=1
```

## Database Schema

Tables:
- `tracked_entity` - Companies being tracked
- `raw_event` - Raw RSS/fetched events
- `resolved_event` - Analyzed and categorized events
- `filing_document` - Downloaded filing documents
- `alert_log` - Alert delivery log

## Project Structure

```
src/market_intel/
├── __init__.py
├── settings.py             # Configuration
├── requirements.txt       # Dependencies
├── alerts/
│   ├── rules.py           # Alert level decisions
│   └── telegram.py         # Telegram client
├── collectors/
│   ├── nse_rss.py         # NSE RSS collector
│   └── corporate_filings.py
├── jobs/
│   └── run_collect.py     # Main entry point
├── processing/
│   ├── deduper.py        # Event hashing
│   ├── entity_resolver.py # Symbol resolution
│   └── trust.py          # Trust scoring
├── services/
│   ├── alert_service.py
│   ├── event_analysis_service.py
│   └── event_ingest_service.py
└── storage/
    ├── db.py             # Database class
    ├── repositories.py  # Data access
    └── schema.sql        # SQL schema
```

## Alert Levels

| Level | Description | Trigger |
|-------|-------------|---------|
| `critical` | High priority | Trust >= 80, Important category |
| `important` | Medium priority | Trust >= 60, Important category |
| `info` | Low priority | Default |

## Testing

```bash
python -m market_intel.jobs.run_collect --db-path ./data/market_intel.duckdb --dry-run-alerts
```

## License

MIT