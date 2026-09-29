import time
from typing import List, Dict, Any
from collections import deque

class EngineLogger:
    """
    In-memory live activity log buffer for in-app diagnostic console.
    Stores the last 150 log events with timestamps and log levels.
    """
    _logs = deque(maxlen=150)

    @classmethod
    def log(cls, message: str, level: str = "INFO"):
        timestamp = time.strftime("%H:%M:%S")
        entry = {
            "time": timestamp,
            "level": level.upper(),
            "message": message
        }
        cls._logs.append(entry)
        # Also print to standard stdout for debugging
        print(f"[{timestamp}] [{level.upper()}] {message}", flush=True)

    @classmethod
    def get_logs(cls) -> List[Dict[str, Any]]:
        return list(cls._logs)

    @classmethod
    def clear(cls):
        cls._logs.clear()

def log_event(message: str, level: str = "INFO"):
    EngineLogger.log(message, level)
