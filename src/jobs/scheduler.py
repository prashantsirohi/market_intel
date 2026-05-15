from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class JobResult:
    job_name: str
    status: str
    started_at: datetime
    completed_at: Optional[datetime]
    items_processed: int = 0
    items_failed: int = 0
    error_message: Optional[str] = None

    @property
    def duration_seconds(self) -> float:
        if self.completed_at and self.started_at:
            return (self.completed_at - self.started_at).total_seconds()
        return 0.0


JobFunc = Callable[[], JobResult]


class Scheduler:
    def __init__(
        self,
        rss_interval_minutes: int = 5,
        api_interval_minutes: int = 15,
        llm_interval_minutes: int = 30,
        backfill_on_start: bool = False,
    ):
        self.rss_interval = timedelta(minutes=rss_interval_minutes)
        self.api_interval = timedelta(minutes=api_interval_minutes)
        self.llm_interval = timedelta(minutes=llm_interval_minutes)
        self.backfill_on_start = backfill_on_start
        
        self._jobs: dict[str, JobFunc] = {}
        self._last_rss_run: Optional[datetime] = None
        self._last_api_run: Optional[datetime] = None
        self._last_llm_run: Optional[datetime] = None
        self._running = False

    def register(self, name: str, job_func: JobFunc) -> None:
        self._jobs[name] = job_func
        logger.info(f"Registered job: {name}")

    def register_default_jobs(
        self,
        rss_job: JobFunc,
        api_job: JobFunc,
        llm_job: Optional[JobFunc] = None,
    ) -> None:
        self.register("rss_fetch", rss_job)
        self.register("api_fetch", api_job)
        if llm_job:
            self.register("llm_analyse", llm_job)

    def should_run_rss(self) -> bool:
        if not self._last_rss_run:
            return True
        return datetime.now() - self._last_rss_run >= self.rss_interval

    def should_run_api(self) -> bool:
        if not self._last_api_run:
            return True
        return datetime.now() - self._last_api_run >= self.api_interval

    def should_run_llm(self) -> bool:
        if not self._last_llm_run:
            return True
        return datetime.now() - self._last_llm_run >= self.llm_interval

    def run_loop(self, stop_event: Any = None, on_complete: Optional[Callable[[JobResult], None]] = None) -> None:
        self._running = True
        logger.info("Scheduler starting")
        
        if self.backfill_on_start:
            logger.info("Running backfill on startup")
            for job_name in ["api_fetch", "llm_analyse"]:
                if job_name in self._jobs:
                    self._run_job(job_name, on_complete)
        
        while self._running:
            try:
                if self.should_run_rss():
                    self._run_job("rss_fetch", on_complete)
                    self._last_rss_run = datetime.now()
                
                if self.should_run_api():
                    self._run_job("api_fetch", on_complete)
                    self._last_api_run = datetime.now()
                
                if self.should_run_llm():
                    self._run_job("llm_analyse", on_complete)
                    self._last_llm_run = datetime.now()
                
                import time
                time.sleep(60)
            except Exception as e:
                logger.error(f"Scheduler loop error: {e}")
        
        logger.info("Scheduler stopped")

    def _run_job(self, name: str, on_complete: Optional[Callable[[JobResult], None]]) -> None:
        if name not in self._jobs:
            return
        
        started = datetime.now()
        logger.info(f"Starting job: {name}")
        
        try:
            result = self._jobs[name]()
            result.completed_at = datetime.now()
            logger.info(f"Job {name} completed: {result.items_processed} processed, {result.items_failed} failed")
        except Exception as e:
            logger.error(f"Job {name} failed: {e}")
            result = JobResult(
                job_name=name,
                status="error",
                started_at=started,
                completed_at=datetime.now(),
                error_message=str(e),
            )
        
        if on_complete:
            on_complete(result)

    def stop(self) -> None:
        self._running = False
        logger.info("Stopping scheduler")


class BackfillRunner:
    def __init__(self, max_days_back: int = 30, batch_size: int = 100):
        self.max_days_back = max_days_back
        self.batch_size = batch_size

    def run(
        self,
        collect_func: Callable[[int, int], int],
        batch_size: Optional[int] = None,
    ) -> int:
        batch_size = batch_size or self.batch_size
        
        logger.info(f"Starting backfill, batch_size={batch_size}")
        
        total_processed = 0
        start_offset = 0
        
        while True:
            processed = collect_func(start_offset, self.batch_size)
            total_processed += processed
            logger.info(f"Backfill batch: offset={start_offset}, processed={processed}")
            
            if processed < self.batch_size:
                break
            
            start_offset += self.batch_size
        
        logger.info(f"Backfill complete: {total_processed} total items")
        return total_processed

    def run_historical(
        self,
        collect_func: Callable[[datetime, datetime], int],
        start_date: datetime,
        end_date: datetime,
    ) -> int:
        logger.info(f"Historical backfill: {start_date.date()} to {end_date.date()}")
        
        total = 0
        current = start_date
        
        while current < end_date:
            next_batch = current + timedelta(days=7)
            if next_batch > end_date:
                next_batch = end_date
            
            processed = collect_func(current, next_batch)
            total += processed
            logger.info(f"Historical batch: {current.date()} to {next_batch.date()}, processed={processed}")
            current = next_batch
        
        logger.info(f"Historical backfill complete: {total} total items")
        return total