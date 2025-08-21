import time
import json
import logging
from collections import deque, defaultdict
from datetime import datetime, timedelta
from typing import Dict, Any, Deque

from database import DatabaseManager

class SystemMonitor:
    """
    A class to monitor the system and generate reports.
    """

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
        self.logger = logging.getLogger(__name__)
        self.time_intervals = {
            "5m": timedelta(minutes=5),
            "30m": timedelta(minutes=30),
            "1h": timedelta(hours=1),
            "6h": timedelta(hours=6),
            "24h": timedelta(hours=24),
        }
        
        # In-memory storage for events with timestamps
        self.api_calls: Dict[str, Deque] = {
            "helius": deque(),
            "rugcheck": deque(),
            "pumpfun": deque(),
        }
        self.helius_credits = deque()

    def record_api_call(self, api_name: str):
        """Records an API call event."""
        if api_name in self.api_calls:
            self.api_calls[api_name].append(datetime.now())

    def record_helius_call(self, method: str, credits: int):
        """Records a Helius API call with credit consumption."""
        self.api_calls["helius"].append(datetime.now())
        self.helius_credits.append((datetime.now(), credits))

    def _prune_events(self):
        """Removes events older than the maximum time interval."""
        max_interval = max(self.time_intervals.values())
        cutoff = datetime.now() - max_interval

        for api_name in self.api_calls:
            while self.api_calls[api_name] and self.api_calls[api_name][0] < cutoff:
                self.api_calls[api_name].popleft()
        
        while self.helius_credits and self.helius_credits[0][0] < cutoff:
            self.helius_credits.popleft()

    def _count_events_in_interval(self, events: Deque, interval: timedelta) -> int:
        """Counts events within a given time interval."""
        cutoff = datetime.now() - interval
        return sum(1 for event_time in events if event_time >= cutoff)

    def _sum_credits_in_interval(self, events: Deque, interval: timedelta) -> int:
        """Sums Helius credits within a given time interval."""
        cutoff = datetime.now() - interval
        return sum(credits for event_time, credits in events if event_time >= cutoff)

    def get_helius_credits_today(self) -> int:
        """Gets the total Helius credits used today."""
        return self._sum_credits_in_interval(self.helius_credits, timedelta(hours=24))

    def collect_metrics(self) -> Dict[str, Any]:
        """Collects all metrics for the report."""
        self._prune_events()
        
        metrics = defaultdict(dict)
        now = datetime.now()

        for key, interval in self.time_intervals.items():
            since_time = now - interval
            
            # API call counts
            metrics["helius_calls"][key] = self._count_events_in_interval(self.api_calls["helius"], interval)
            metrics["rugcheck_calls"][key] = self._count_events_in_interval(self.api_calls["rugcheck"], interval)
            metrics["pumpfun_calls"][key] = self._count_events_in_interval(self.api_calls["pumpfun"], interval)
            
            # Helius credits
            metrics["helius_credits_spent"][key] = self._sum_credits_in_interval(self.helius_credits, interval)
            
            # Database metrics
            metrics["new_tokens"][key] = self.db_manager.get_new_tokens_count(since_time)
            metrics["new_early_adopters"][key] = self.db_manager.get_new_early_adopters_count(since_time)
            metrics["pump_tokens_updates"][key] = self.db_manager.get_pump_tokens_updates_count(since_time)

        return dict(metrics)

    def generate_report(self) -> str:
        """Generates a JSON report of the current metrics."""
        report = {
            "timestamp": datetime.now().isoformat(),
            "metrics": self.collect_metrics()
        }
        return json.dumps(report, indent=2)

    def run(self):
        """
        Runs the monitoring loop.
        """
        self.logger.info("Starting system monitor...")
        while True:
            try:
                report = self.generate_report()
                self.logger.info("System Monitor Report:\n%s", report)
                # In a real application, this report could be written to a file,
                # sent to a monitoring service, etc.
            except Exception as e:
                self.logger.error(f"Error generating system monitor report: {e}", exc_info=True)
            
            time.sleep(30)

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    from database import db
    monitor = SystemMonitor(db)
    monitor.run()
