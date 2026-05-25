from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def run_sync(
    limit: Optional[int] = None,
    force: bool = False,
    db_path: str = "./data/screener_financials.db",
    master_db_path: str = "./data/masterdata.db",
    username: Optional[str] = None,
    password: Optional[str] = None,
    throttle_sec: float = 2.0
) -> None:
    """Read tickers from masterdata.db, download, parse, and store them in screener_financials.db."""
    import sqlite3
    from collectors.screener import ScreenerClient
    from storage.financials_db import FinancialsDatabase
    from settings import settings

    # Initialize client and DB
    client = ScreenerClient(
        username=username,
        password=password,
        data_dir=settings.data_dir
    )
    fin_db = FinancialsDatabase(db_path)
    
    # 1. Get already synced tickers to skip them
    synced = set() if force else fin_db.get_synced_symbols()
    logger.info("Found %d already synced symbols.", len(synced))
    
    # 2. Get tickers from masterdata.db
    master_path = Path(master_db_path)
    if not master_path.exists():
        logger.error("Master database not found at %s", master_path)
        return
        
    logger.info("Loading tickers from master database: %s", master_path)
    master_conn = sqlite3.connect(master_path)
    try:
        cursor = master_conn.cursor()
        cursor.execute("""
            SELECT DISTINCT COALESCE(nse_symbol, symbol_id) as ticker 
            FROM symbols 
            WHERE (exchange = 'NSE' OR nse_symbol IS NOT NULL) 
              AND ticker IS NOT NULL 
              AND ticker != ''
            ORDER BY mcap DESC
        """)
        all_tickers = [row[0] for row in cursor.fetchall()]
    except Exception as e:
        logger.error("Failed to query master database symbols: %s", e)
        return
    finally:
        master_conn.close()
        
    # Filter out already synced tickers
    tickers_to_sync = [t for t in all_tickers if t not in synced]
    logger.info("Total tickers in master database: %d", len(all_tickers))
    logger.info("Tickers remaining to sync: %d", len(tickers_to_sync))
    
    if limit is not None:
        tickers_to_sync = tickers_to_sync[:limit]
        logger.info("Limiting sync run to %d tickers.", len(tickers_to_sync))
        
    if not tickers_to_sync:
        logger.info("No tickers to sync.")
        return
        
    success_count = 0
    fail_count = 0
    
    for idx, ticker in enumerate(tickers_to_sync):
        logger.info("[%d/%d] Syncing ticker: %s", idx + 1, len(tickers_to_sync), ticker)
        try:
            if idx > 0 and throttle_sec > 0:
                logger.info("Throttling for %.2f seconds...", throttle_sec)
                time.sleep(throttle_sec)
                
            # Download and parse
            data = client.fetch_company_data(ticker, force_download=force)
            
            # Save to financials SQLite DB
            fin_db.save_company_financials(ticker, data)
            success_count += 1
            
        except Exception as exc:
            logger.error("Failed to sync ticker %s: %s", ticker, exc)
            fail_count += 1
            # Continue with next symbol
            continue
            
    logger.info("Sync cycle completed. Success: %d, Failed: %d", success_count, fail_count)
