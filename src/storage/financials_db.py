from __future__ import annotations

import logging
import sqlite3
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Predefined standard metrics for the catalog
PREDEFINED_METRICS = {
    # P&L / Income Statement
    "sales": ("Sales", "P&L", "income_statement", "INR", "cr", True),
    "expenses": ("Expenses", "P&L", "income_statement", "INR", "cr", False),
    "operating_profit": ("Operating profit", "P&L", "income_statement", "INR", "cr", True),
    "other_income": ("Other income", "P&L", "income_statement", "INR", "cr", True),
    "depreciation": ("Depreciation", "P&L", "income_statement", "INR", "cr", False),
    "interest": ("Interest", "P&L", "income_statement", "INR", "cr", False),
    "profit_before_tax": ("Profit before tax", "P&L", "income_statement", "INR", "cr", True),
    "tax_expense": ("Tax", "P&L", "income_statement", "INR", "cr", False),
    "net_profit": ("Net profit", "P&L", "income_statement", "INR", "cr", True),
    "dividend_amount": ("Dividend Amount", "P&L", "income_statement", "INR", "cr", True),
    "eps": ("EPS", "P&L", "income_statement", "INR", "units", True),
    "dividend_payout_pct": ("Dividend Payout", "Ratio", "income_statement", "percent", "units", True),
    "opm_pct": ("OPM", "Ratio", "income_statement", "percent", "units", True),

    # Balance Sheet
    "equity_share_capital": ("Equity Share Capital", "Equity", "balance_sheet", "INR", "cr", True),
    "reserves": ("Reserves", "Equity", "balance_sheet", "INR", "cr", True),
    "borrowings": ("Borrowings", "Liability", "balance_sheet", "INR", "cr", False),
    "other_liabilities": ("Other Liabilities", "Liability", "balance_sheet", "INR", "cr", False),
    "total_liabilities": ("Total Liabilities", "Liability", "balance_sheet", "INR", "cr", None),
    "net_block": ("Net Block", "Asset", "balance_sheet", "INR", "cr", True),
    "capital_work_in_progress": ("Capital Work in Progress", "Asset", "balance_sheet", "INR", "cr", True),
    "investments": ("Investments", "Asset", "balance_sheet", "INR", "cr", True),
    "other_assets": ("Other Assets", "Asset", "balance_sheet", "INR", "cr", True),
    "total_assets": ("Total Assets", "Asset", "balance_sheet", "INR", "cr", None),
    "receivables": ("Receivables", "Asset", "balance_sheet", "INR", "cr", None),
    "inventory": ("Inventory", "Asset", "balance_sheet", "INR", "cr", None),
    "cash_and_bank": ("Cash & Bank", "Asset", "balance_sheet", "INR", "cr", True),
    "equity_shares_outstanding": ("No. of Equity Shares", "Equity", "balance_sheet", "count", "units", None),
    "new_bonus_shares": ("New Bonus Shares", "Equity", "balance_sheet", "count", "units", None),
    "adjusted_equity_shares_cr": ("Adjusted Equity Shares in Cr", "Equity", "balance_sheet", "count", "cr", None),

    # Cash Flow
    "cash_from_operations": ("Cash from Operating Activity", "Cash Flow", "cash_flow", "INR", "cr", True),
    "cash_from_investing": ("Cash from Investing Activity", "Cash Flow", "cash_flow", "INR", "cr", None),
    "cash_from_financing": ("Cash from Financing Activity", "Cash Flow", "cash_flow", "INR", "cr", None),
    "net_cash_flow": ("Net Cash Flow", "Cash Flow", "cash_flow", "INR", "cr", True),
}

# Raw label mapping to clean metric IDs
RAW_LABEL_MAPPING = {
    "sales": "sales",
    "expenses": "expenses",
    "operating profit": "operating_profit",
    "other income": "other_income",
    "depreciation": "depreciation",
    "interest": "interest",
    "profit before tax": "profit_before_tax",
    "tax": "tax_expense",
    "net profit": "net_profit",
    "dividend amount": "dividend_amount",
    "eps": "eps",
    "dividend payout": "dividend_payout_pct",
    "opm": "opm_pct",
    "equity share capital": "equity_share_capital",
    "reserves": "reserves",
    "borrowings": "borrowings",
    "other liabilities": "other_liabilities",
    "total liabilities": "total_liabilities",
    "net block": "net_block",
    "capital work in progress": "capital_work_in_progress",
    "investments": "investments",
    "other assets": "other_assets",
    "total assets": "total_assets",
    "receivables": "receivables",
    "inventory": "inventory",
    "cash & bank": "cash_and_bank",
    "no. of equity shares": "equity_shares_outstanding",
    "new bonus shares": "new_bonus_shares",
    "adjusted equity shares in cr": "adjusted_equity_shares_cr",
    "cash from operating activity": "cash_from_operations",
    "cash from investing activity": "cash_from_investing",
    "cash from financing activity": "cash_from_financing",
    "net cash flow": "net_cash_flow",
}


class FinancialsDatabase:
    """Database manager for storing Screener.in company financials using SQLite (Corrected Schema)."""

    def __init__(self, db_path: str = "./data/screener_financials.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self) -> None:
        """Initialize the database schema and pre-populate the metric catalog."""
        logger.info("Initializing relational database schema in %s", self.db_path)
        with self._get_connection() as conn:
            # 1. Company Snapshot
            conn.execute("""
                CREATE TABLE IF NOT EXISTS screener_company_snapshot (
                    symbol TEXT NOT NULL,
                    as_of_date DATE NOT NULL,
                    face_value REAL,
                    market_cap_cr REAL,
                    source TEXT NOT NULL DEFAULT 'screener',
                    sync_batch_id TEXT,
                    synced_at TIMESTAMP NOT NULL,
                    PRIMARY KEY (symbol, as_of_date, source)
                );
            """)

            # 2. Market Valuation
            conn.execute("""
                CREATE TABLE IF NOT EXISTS screener_market_valuation (
                    symbol TEXT NOT NULL,
                    date DATE NOT NULL,
                    price REAL,
                    market_cap_cr REAL,
                    pe REAL,
                    pb REAL,
                    ev_ebitda REAL,
                    dividend_yield REAL,
                    source TEXT NOT NULL DEFAULT 'screener',
                    sync_batch_id TEXT,
                    synced_at TIMESTAMP NOT NULL,
                    PRIMARY KEY (symbol, date, source)
                );
            """)

            # 3. Metric Catalog
            conn.execute("""
                CREATE TABLE IF NOT EXISTS screener_metric_catalog (
                    metric_id TEXT PRIMARY KEY,
                    metric_name TEXT NOT NULL,
                    category TEXT,
                    statement_type TEXT,
                    unit TEXT,
                    scale TEXT,
                    higher_is_better BOOLEAN,
                    source TEXT DEFAULT 'screener'
                );
            """)

            # 4. Financials (incorporating available_at)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS screener_financials (
                    symbol TEXT NOT NULL,
                    period_type TEXT NOT NULL,
                    report_date DATE NOT NULL,
                    metric_id TEXT NOT NULL,
                    value REAL,
                    available_at DATE NOT NULL,
                    source TEXT DEFAULT 'screener',
                    sync_batch_id TEXT,
                    synced_at TIMESTAMP NOT NULL,
                    PRIMARY KEY (symbol, period_type, report_date, metric_id, available_at),
                    FOREIGN KEY (metric_id) REFERENCES screener_metric_catalog(metric_id)
                );
            """)

            # Prepopulate standard metrics
            for m_id, m_info in PREDEFINED_METRICS.items():
                conn.execute(
                    """
                    INSERT OR IGNORE INTO screener_metric_catalog (
                        metric_id, metric_name, category, statement_type, unit, scale, higher_is_better
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (m_id, m_info[0], m_info[1], m_info[2], m_info[3], m_info[4], m_info[5]),
                )

            conn.commit()

    def _normalize_metric(self, raw_name: str) -> tuple[str, str]:
        """Normalize a raw metric name into a metric_id.

        Returns:
            A tuple of (metric_id, display_name).
        """
        raw_clean = raw_name.lower().strip()
        # Look up in standard mapping
        if raw_clean in RAW_LABEL_MAPPING:
            metric_id = RAW_LABEL_MAPPING[raw_clean]
            display_name = PREDEFINED_METRICS[metric_id][0]
            return metric_id, display_name

        # Fallback dynamic metric normalization
        display_name = raw_name.strip()
        metric_id = re.sub(r"[^a-z0-9]+", "_", display_name.lower()).strip("_")
        return metric_id, display_name

    def _ensure_metric_in_catalog(self, conn: sqlite3.Connection, metric_id: str, display_name: str) -> None:
        """Helper to dynamically add a custom metric to the catalog if not already present."""
        conn.execute(
            """
            INSERT OR IGNORE INTO screener_metric_catalog (
                metric_id, metric_name, category, statement_type, unit, scale, higher_is_better
            ) VALUES (?, ?, 'other', 'unknown', 'units', 'units', NULL)
            """,
            (metric_id, display_name),
        )

    def _calculate_available_at(self, period_type: str, report_date_str: str) -> str:
        """Calculate the available_at date based on the report_date and period_type."""
        try:
            dt = datetime.strptime(report_date_str, "%Y-%m-%d")
            if period_type == "quarterly":
                avail_dt = dt + timedelta(days=45)
            else:
                # Default heuristic for annual statements (90 days)
                avail_dt = dt + timedelta(days=90)
            return avail_dt.strftime("%Y-%m-%d")
        except Exception:
            return report_date_str

    def _compute_market_valuations(self, symbol: str, data: dict[str, Any], synced_at: str, sync_batch_id: str | None = None) -> list[tuple[Any, ...]]:
        """Calculate pe, pb, ev_ebitda, dividend_yield historically from the data."""
        pl = data.get("profit_loss", {})
        bs = data.get("balance_sheet", {})
        derived = data.get("derived", {})
        
        prices = derived.get("prices", {})
        shares_cr_dict = derived.get("Adjusted Equity Shares in Cr", {})
        net_profit_dict = pl.get("Net profit", {})
        share_capital_dict = bs.get("Equity Share Capital", {})
        reserves_dict = bs.get("Reserves", {})
        borrowings_dict = bs.get("Borrowings", {})
        cash_bank_dict = bs.get("Cash & Bank", {})
        op_profit_dict = pl.get("Operating profit", pl.get("Operating Profit", {}))
        dividend_dict = pl.get("Dividend Amount", {})
        
        rows = []
        
        for date_str, price in prices.items():
            if price is None:
                continue
                
            p = float(price)
            mcap = None
            pe = None
            pb = None
            ev_ebitda = None
            div_yield = None
            
            # 1. Market Cap
            shares_cr = shares_cr_dict.get(date_str)
            if shares_cr is not None:
                try:
                    mcap = p * float(shares_cr)
                except Exception:
                    pass
            
            # 2. P/E
            net_profit = net_profit_dict.get(date_str)
            if net_profit is not None and mcap is not None:
                try:
                    np = float(net_profit)
                    if np != 0:
                        pe = mcap / np
                except Exception:
                    pass
                    
            # 3. P/B
            share_cap = share_capital_dict.get(date_str)
            reserves = reserves_dict.get(date_str)
            if share_cap is not None and reserves is not None and mcap is not None:
                try:
                    book_value = float(share_cap) + float(reserves)
                    if book_value != 0:
                        pb = mcap / book_value
                except Exception:
                    pass
                    
            # 4. EV / EBITDA
            borrowings = borrowings_dict.get(date_str)
            cash_bank = cash_bank_dict.get(date_str)
            op_profit = op_profit_dict.get(date_str)
            if op_profit is None:
                # Reconstruct operating profit: PBT + Interest + Depreciation - Other Income
                pbt = pl.get("Profit before tax", {}).get(date_str)
                interest = pl.get("Interest", {}).get(date_str, 0) or 0
                depr = pl.get("Depreciation", {}).get(date_str, 0) or 0
                other_inc = pl.get("Other Income", {}).get(date_str, 0) or 0
                if pbt is not None:
                    try:
                        op_profit = float(pbt) + float(interest) + float(depr) - float(other_inc)
                    except Exception:
                        pass
                        
            if op_profit is not None and mcap is not None:
                try:
                    b_val = float(borrowings) if borrowings is not None else 0.0
                    c_val = float(cash_bank) if cash_bank is not None else 0.0
                    ev = mcap + b_val - c_val
                    ebitda = float(op_profit)
                    if ebitda != 0:
                        ev_ebitda = ev / ebitda
                except Exception:
                    pass
                    
            # 5. Dividend Yield
            dividend = dividend_dict.get(date_str)
            if dividend is not None and mcap is not None:
                try:
                    div = float(dividend)
                    if mcap > 0:
                        div_yield = (div / mcap) * 100
                except Exception:
                    pass
                    
            rows.append((
                symbol,
                date_str,
                p,
                mcap,
                pe,
                pb,
                ev_ebitda,
                div_yield,
                "screener",
                sync_batch_id,
                synced_at
            ))
            
        return rows

    def save_company_financials(self, symbol: str, data: dict[str, Any], sync_batch_id: str | None = None) -> None:
        """Save the company snapshot, valuation, and financials statements in a transaction."""
        symbol = symbol.upper().strip()
        metadata = data.get("metadata", {})
        synced_at = datetime.now().isoformat()
        sync_date = datetime.now().strftime("%Y-%m-%d")

        with self._get_connection() as conn:
            # 1. Insert screener_company_snapshot
            conn.execute(
                """
                INSERT OR REPLACE INTO screener_company_snapshot (
                    symbol, as_of_date, face_value, market_cap_cr, source, sync_batch_id, synced_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol,
                    sync_date,
                    metadata.get("face_value"),
                    metadata.get("market_cap_cr"),
                    "screener",
                    sync_batch_id,
                    synced_at,
                ),
            )

            # 2. Insert screener_market_valuation
            valuation_rows = self._compute_market_valuations(symbol, data, synced_at, sync_batch_id)
            if valuation_rows:
                conn.executemany(
                    """
                    INSERT OR REPLACE INTO screener_market_valuation (
                        symbol, date, price, market_cap_cr, pe, pb, ev_ebitda, dividend_yield, source, sync_batch_id, synced_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    valuation_rows,
                )

            # 3. Insert screener_financials
            sections = {
                "profit_loss": "annual",
                "quarters": "quarterly",
                "balance_sheet": "annual",
                "cash_flow": "annual",
                "derived": "annual",
            }

            financials_rows = []

            for section_key, period_type in sections.items():
                section_data = data.get(section_key, {})
                for raw_metric_name, date_dict in section_data.items():
                    # Skip specific non-financial columns
                    raw_clean = raw_metric_name.lower().strip()
                    if raw_clean in ["face value", "prices"]:
                        continue

                    # Get normalized metric details
                    metric_id, display_name = self._normalize_metric(raw_metric_name)
                    
                    # Ensure metric catalog record exists
                    self._ensure_metric_in_catalog(conn, metric_id, display_name)

                    if isinstance(date_dict, dict):
                        for date_str, val in date_dict.items():
                            if val is not None:
                                try:
                                    val_float = float(val)
                                    available_at = self._calculate_available_at(period_type, date_str)
                                    financials_rows.append((
                                        symbol,
                                        period_type,
                                        date_str,
                                        metric_id,
                                        val_float,
                                        available_at,
                                        "screener",
                                        sync_batch_id,
                                        synced_at,
                                    ))
                                except (ValueError, TypeError):
                                    continue

            if financials_rows:
                conn.executemany(
                    """
                    INSERT OR REPLACE INTO screener_financials (
                        symbol, period_type, report_date, metric_id, value, available_at, source, sync_batch_id, synced_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    financials_rows,
                )

            conn.commit()
            logger.info("Saved financials for %s: %d records added/updated.", symbol, len(financials_rows))

    def get_synced_symbols(self) -> set[str]:
        """Return a set of all stock symbols that have been synced successfully."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT symbol FROM screener_company_snapshot")
            rows = cursor.fetchall()
            return {row["symbol"] for row in rows}

    def get_company_data(self, symbol: str) -> dict[str, Any] | None:
        """Fetch all stored financials data for a company symbol (reconstructs structure for display)."""
        symbol = symbol.upper().strip()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Fetch latest snapshot
            cursor.execute(
                """
                SELECT face_value, market_cap_cr
                FROM screener_company_snapshot
                WHERE symbol = ?
                ORDER BY as_of_date DESC LIMIT 1
                """,
                (symbol,),
            )
            meta_row = cursor.fetchone()
            if not meta_row:
                return None

            metadata = dict(meta_row)
            metadata["symbol"] = symbol

            # Fetch financials with catalog descriptions
            cursor.execute(
                """
                SELECT f.period_type, f.report_date, f.metric_id, f.value, c.metric_name, c.category, c.statement_type
                FROM screener_financials f
                JOIN screener_metric_catalog c ON f.metric_id = c.metric_id
                WHERE f.symbol = ?
                """,
                (symbol,),
            )
            fin_rows = cursor.fetchall()

            # Reconstruct original structure
            result: dict[str, Any] = {
                "metadata": metadata,
                "profit_loss": {},
                "quarters": {},
                "balance_sheet": {},
                "cash_flow": {},
                "derived": {}
            }

            for row in fin_rows:
                period_type = row["period_type"]
                report_date = row["report_date"]
                metric_name = row["metric_name"]
                statement_type = row["statement_type"]
                value = row["value"]

                if period_type == "quarterly":
                    result["quarters"].setdefault(metric_name, {})[report_date] = value
                elif statement_type == "income_statement":
                    result["profit_loss"].setdefault(metric_name, {})[report_date] = value
                elif statement_type == "balance_sheet":
                    result["balance_sheet"].setdefault(metric_name, {})[report_date] = value
                elif statement_type == "cash_flow":
                    result["cash_flow"].setdefault(metric_name, {})[report_date] = value
                else:
                    result["derived"].setdefault(metric_name, {})[report_date] = value

            # Reconstruct historical price series
            cursor.execute("SELECT date, price FROM screener_market_valuation WHERE symbol = ?", (symbol,))
            prices = cursor.fetchall()
            result["derived"]["prices"] = {row["date"]: row["price"] for row in prices}

            return result
