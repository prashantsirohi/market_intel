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
- **Security master V1**: Audited official NSE/BSE active-listing snapshots joined by exact ISIN
- **High-value shadow filter**: Versioned metadata-first NSE/BSE routing with coverage receipts and selective attachment eligibility

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
- `announcement_collection_run` - Immutable source-window coverage receipts for the V1 shadow collector
- `announcement_filter_decision` - Auditable `KEEP`, `FETCH_ATTACHMENT`, or `DROP_METADATA_ONLY` decisions
- `listing_sync_run` - Immutable per-exchange listing-master sync receipts
- `listed_security_observation` - Normalized listing observations with source-row hashes
- `listed_security_current` - Latest completed NSE/BSE observations per exchange
- `security_listing_membership_current` - Exact-ISIN `NSE_ONLY`, `BSE_ONLY`, and `DUAL` membership

## Security master V1

Synchronize the official active-equity masters before collecting announcements:

```bash
PYTHONPATH=src ./.venv/bin/python -m jobs.run_security_master_v1 sync \
  --db-path ./data/market_intel.duckdb \
  --effective-date YYYY-MM-DD \
  --exchanges NSE,BSE
```

Inspect the latest completed cross-exchange snapshot without making network calls:

```bash
PYTHONPATH=src ./.venv/bin/python -m jobs.run_security_master_v1 report \
  --db-path ./data/market_intel.duckdb
```

The master stores normalized identity metadata, source and row hashes, and sync
coverage—not raw exchange files. `tracked_entity` remains an operator watchlist.
Announcements are enriched by exact exchange identifier/ISIN; dual-listed BSE
events receive their canonical NSE symbol while retaining BSE provenance. The
official active lists are current snapshots with temporal trust
`LATEST_ONLY_OBSERVED_AT_SYNC`; the sync CLI rejects a backdated effective date.

## High-value filter V1

Run a metadata-only shadow collection first. This stores every announcement's
metadata and decision but downloads no PDFs and performs no LLM calls. The job
fails fast unless every requested exchange has a completed security-master
snapshot:

```bash
PYTHONPATH=src ./.venv/bin/python -m jobs.run_high_value_v1 collect \
  --db-path ./data/market_intel.duckdb \
  --from-date YYYY-MM-DD --to-date YYYY-MM-DD \
  --sources nse_api,bse_corp
```

After reviewing the decision mix, add `--download-selected` to download and
extract attachments only for `KEEP` and `FETCH_ATTACHMENT`. Shadow PDF
processing never invokes the operational LLM enrichment path.

Measure the frozen starter fixture with:

```bash
PYTHONPATH=src ./.venv/bin/python -m jobs.run_high_value_v1 calibrate \
  --labels configs/high_value_filter_baseline_v1.json
```

The fixture is a smoke baseline, not evidence of production precision or
recall. Replace or extend it with reviewed live announcement labels before
promoting any rule successor.

Export a deterministic live review set from exact completed collection runs:

```bash
PYTHONPATH=src ./.venv/bin/python -m jobs.run_high_value_v1 export-review \
  --db-path ./data/market_intel.duckdb \
  --collection-run-ids <nse-run-id>,<bse-run-id> \
  --cohort-file /path/to/capex_baseline_v1.json \
  --output /path/to/high-value-review-v1.json
```

The default export samples 50 `KEEP`, 50 `FETCH_ATTACHMENT`, and 100
`DROP_METADATA_ONLY` decisions using deterministic source-and-membership
strata, then adds every matching cohort announcement. It refuses incomplete
receipts and existing output files. Reviewers replace each `expected: null`
with `HIGH_VALUE` or `NOT_HIGH_VALUE`; the resulting file can be passed
directly to the `calibrate` command. By default, calibration requires every
case to be labeled. During review, `calibrate --allow-partial` measures only
the labeled subset and reports label coverage; a partial result is diagnostic
and cannot promote the policy.

## J-curve targeted historical backfill V1

The backfill reads only the completed `PRIMARY_RESEARCH` queue from an
immutable research-screener discovery run. Each bounded chunk fetches complete
metadata for the requested exchange so its source coverage receipt remains
truthful, then retains exact cohort ISIN/exchange identities before ingestion.
Request NSE for every NSE-listed cohort member and add BSE only when the frozen
cohort contains a BSE-only member. Chunks are newest-first, independently
receipted, and resumable. Exact cross-listing duplicates use ISIN, publication
date, and normalized title with NSE preferred.

Preview the immutable plan without changing either database:

```bash
PYTHONPATH=src ./.venv/bin/python -m jobs.run_jcurve_backfill_v1 plan \
  --research-store /path/to/research_screener/control_plane.duckdb \
  --discovery-run-id <completed-jcurve-discovery-run-id> \
  --from-date YYYY-MM-DD --to-date YYYY-MM-DD \
  --sources nse_api,bse_corp --chunk-days 31
```

After backing up `market_intel.duckdb`, run or resume collection with the same
arguments plus `--db-path`. `--max-chunks 1` is the recommended live canary;
rerunning the full command skips completed chunks. Inspect progress with the
`status` subcommand and the returned `backfill_run_id`.

Once metadata is complete, download only attachments carrying a strong
J-curve signal (`CAPEX`, `CAPACITY`, facility, commissioning, project finance,
demand path, order award, or project-adverse evidence):

```bash
PYTHONPATH=src ./.venv/bin/python -m jobs.run_jcurve_backfill_v1 \
  download-attachments \
  --db-path /path/to/market_intel.duckdb \
  --backfill-run-id <completed-backfill-run-id>
```

The attachment run is content-addressed, accepts only fetchable HTTP(S) URLs,
checksum-validates existing files, stores new PDFs beside the configured
database under `market_intel_pdfs/`, never invokes LLM enrichment, and is
resumable with `--max-items`. It also repairs matching cohort events that were
already present before the parent backfill and therefore deduplicated on insert;
relative legacy file paths are redownloaded into the absolute external store.

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
