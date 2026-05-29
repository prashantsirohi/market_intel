from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any
import pandas as pd
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)


class ScreenerClient:
    """Client for downloading and parsing Excel financial statements from Screener.in."""

    def __init__(
        self,
        username: str | None = None,
        password: str | None = None,
        data_dir: str = "./data",
        storage_state_path: str | None = None,
    ):
        self.username = username or os.environ.get("SCREENER_USERNAME")
        self.password = password or os.environ.get("SCREENER_PASSWORD")
        if not self.username or not self.password:
            raise ValueError(
                "Screener username and password must be provided or set via "
                "SCREENER_USERNAME and SCREENER_PASSWORD environment variables."
            )
        self.data_dir = Path(data_dir)
        self.exports_dir = self.data_dir / "exports"
        self.exports_dir.mkdir(parents=True, exist_ok=True)
        
        if storage_state_path:
            self.storage_state_path = Path(storage_state_path)
        else:
            cache_dir = self.data_dir / "cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            self.storage_state_path = cache_dir / "screener_auth_state.json"

    def download_excel(self, ticker: str, force_download: bool = False) -> str:
        """Download the Screener Excel file for the given ticker.

        Returns:
            The path to the downloaded Excel file.
        """
        ticker = ticker.upper().strip()
        output_path = self.exports_dir / f"{ticker}_screener.xlsx"
        
        if output_path.exists() and not force_download:
            logger.info("Excel file for %s already exists at %s. Skipping download.", ticker, output_path)
            return str(output_path)
            
        logger.info("Starting Playwright download for %s...", ticker)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            
            # Use saved storage state if available
            if self.storage_state_path.exists():
                logger.info("Loading session from %s", self.storage_state_path)
                context = browser.new_context(storage_state=str(self.storage_state_path))
            else:
                logger.info("No saved session found. Starting new session.")
                context = browser.new_context()
                
            page = context.new_page()
            
            # Check if we are logged in by visiting dashboard page
            logger.info("Checking login status...")
            page.goto("https://www.screener.in/dash/")
            
            if page.url.rstrip("/") != "https://www.screener.in/dash":
                logger.info("Not logged in (currently at %s). Performing login...", page.url)
                page.goto("https://www.screener.in/login/?next=/dash/")
                page.fill("input[name='username']", self.username)
                page.fill("input[name='password']", self.password)
                page.click("button[type='submit']")
                page.wait_for_url("https://www.screener.in/dash/")
                logger.info("Login successful. Saving storage state.")
                context.storage_state(path=str(self.storage_state_path))
            else:
                logger.info("Already logged in.")
                
            # Navigate to company page
            company_url = f"https://www.screener.in/company/{ticker}/"
            logger.info("Navigating to %s...", company_url)
            page.goto(company_url)
            
            title = page.title()
            if "Page not found" in title or "404" in title:
                raise ValueError(f"Company ticker '{ticker}' not found on Screener.in")
                
            logger.info("Locating 'Export to Excel' button...")
            button_selector = (
                "button:has-text('EXPORT TO EXCEL'), "
                "button:has-text('Export to Excel'), "
                "button:has-text('Export to excel')"
            )
            
            try:
                page.wait_for_selector(button_selector, timeout=10000)
            except Exception:
                screenshot_path = self.data_dir / f"error_screener_{ticker}.png"
                page.screenshot(path=str(screenshot_path))
                raise RuntimeError(
                    f"Could not find Export to Excel button. Screenshot saved to {screenshot_path}"
                )
                
            logger.info("Triggering download...")
            with page.expect_download() as download_info:
                page.click(button_selector)
                
            download = download_info.value
            download.save_as(str(output_path))
            logger.info(
                "Successfully downloaded Excel to %s (size: %d bytes)",
                output_path, os.path.getsize(output_path)
            )
            
            browser.close()
            
        return str(output_path)

    def parse_excel(self, file_path: str) -> dict[str, Any]:
        """Parse the Screener Excel file's 'Data Sheet' tab into a structured dictionary."""
        file_path_obj = Path(file_path)
        if not file_path_obj.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
            
        df = pd.read_excel(file_path_obj, sheet_name="Data Sheet", header=None)
        
        result: dict[str, Any] = {
            "metadata": {},
            "profit_loss": {},
            "quarters": {},
            "balance_sheet": {},
            "cash_flow": {},
            "derived": {}
        }
        
        current_section = None
        section_dates = []
        seen_assets = False
        
        def clean_label(val: Any) -> str:
            if pd.isna(val):
                return ""
            return str(val).strip()

        i = 0
        num_rows = len(df)
        while i < num_rows:
            row = df.iloc[i]
            col0 = clean_label(row[0])
            
            if not col0:
                i += 1
                continue
                
            # Check for section boundaries
            if col0 == "COMPANY NAME":
                result["metadata"]["company_name"] = clean_label(row[1])
                i += 1
                continue
            elif col0 in ["LATEST VERSION", "CURRENT VERSION"]:
                result["metadata"][col0.lower().replace(" ", "_")] = clean_label(row[1])
                i += 1
                continue
            elif col0 == "Face Value":
                result["metadata"]["face_value"] = row[1]
                i += 1
                continue
            elif col0 == "Current Price":
                result["metadata"]["current_price"] = row[1]
                i += 1
                continue
            elif col0 == "Market Capitalization":
                result["metadata"]["market_cap_cr"] = row[1]
                i += 1
                continue
            elif col0 == "META":
                current_section = "metadata"
                i += 1
                continue
            elif col0 == "PROFIT & LOSS":
                current_section = "profit_loss"
                i += 1
                next_row = df.iloc[i]
                if clean_label(next_row[0]) == "Report Date":
                    section_dates = [str(val).split()[0] for val in next_row[1:] if pd.notnull(val)]
                i += 1
                continue
            elif col0 == "Quarters":
                current_section = "quarters"
                i += 1
                next_row = df.iloc[i]
                if clean_label(next_row[0]) == "Report Date":
                    section_dates = [str(val).split()[0] for val in next_row[1:] if pd.notnull(val)]
                i += 1
                continue
            elif col0 == "BALANCE SHEET":
                current_section = "balance_sheet"
                i += 1
                next_row = df.iloc[i]
                if clean_label(next_row[0]) == "Report Date":
                    section_dates = [str(val).split()[0] for val in next_row[1:] if pd.notnull(val)]
                i += 1
                continue
            elif col0 == "CASH FLOW:":
                current_section = "cash_flow"
                i += 1
                next_row = df.iloc[i]
                if clean_label(next_row[0]) == "Report Date":
                    section_dates = [str(val).split()[0] for val in next_row[1:] if pd.notnull(val)]
                i += 1
                continue
            elif col0 == "PRICE:":
                price_dates = section_dates
                prices = [val for val in row[1:] if pd.notnull(val)]
                result["derived"]["prices"] = dict(zip(price_dates, prices))
                i += 1
                continue
            elif col0 == "DERIVED:":
                current_section = "derived"
                i += 1
                continue
                
            # Parse data row inside a section
            if current_section and current_section != "metadata":
                label = col0
                if current_section == "balance_sheet":
                    if col0 in ["Net Block", "Capital Work in Progress", "Investments", "Other Assets"]:
                        seen_assets = True
                    if col0 == "Total":
                        label = "Total Assets" if seen_assets else "Total Liabilities"
                values = [val if pd.notnull(val) else None for val in row[1:]]
                
                date_val_dict = {}
                for idx, date_str in enumerate(section_dates):
                    if idx < len(values):
                        date_val_dict[date_str] = values[idx]
                
                if current_section == "profit_loss":
                    result["profit_loss"][label] = date_val_dict
                elif current_section == "quarters":
                    result["quarters"][label] = date_val_dict
                elif current_section == "balance_sheet":
                    result["balance_sheet"][label] = date_val_dict
                elif current_section == "cash_flow":
                    result["cash_flow"][label] = date_val_dict
                elif current_section == "derived":
                    result["derived"][label] = date_val_dict
                    
            i += 1
            
        return result

    def fetch_company_data(self, ticker: str, force_download: bool = False) -> dict[str, Any]:
        """Download and parse Screener data for a company ticker."""
        excel_path = self.download_excel(ticker, force_download=force_download)
        return self.parse_excel(excel_path)
