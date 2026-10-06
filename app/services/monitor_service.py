import os
import time
import platform
import logging
from typing import Dict

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

logger = logging.getLogger("GravityNAS.MonitorService")

class MonitorService:
    def __init__(self, storage_path: str):
        self.storage_path = storage_path
        self._cache = {"data": None, "time": 0}

    def get_stats(self) -> Dict:
        now = time.time()
        if self._cache["data"] and (now - self._cache["time"] < 5):
            return self._cache["data"]

        stats = {
            "cpu_percent": 0, "ram_percent": 0, "disk_percent": 0,
            "cpu_temp": 0, "uptime": "N/A", "os_info": f"{platform.system()} {platform.release()}"
        }

        if HAS_PSUTIL:
            try:
                usage = psutil.disk_usage(self.storage_path)
                mem = psutil.virtual_memory()
                stats.update({
                    "cpu_percent": psutil.cpu_percent(interval=0.1),
                    "ram_percent": mem.percent,
                    "ram_used": self._fmt(mem.used),
                    "disk_percent": usage.percent,
                    "disk_free": self._fmt(usage.free),
                    "disk_total": self._fmt(usage.total),
                    "uptime": self._get_uptime()
                })
                stats["cpu_temp"] = self._get_cpu_temp()
            except Exception as e:
                logger.error(f"Error fetching system stats: {e}")

        self._cache = {"data": stats, "time": now}
        return stats

    def _get_cpu_temp(self) -> float:
        if os.path.exists("/sys/class/thermal/thermal_zone0/temp"):
            with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                return round(int(f.read()) / 1000, 1)
        return 0.0

    def _get_uptime(self) -> str:
        diff = time.time() - psutil.boot_time()
        days = int(diff // 86400)
        hours = int((diff % 86400) // 3600)
        return f"{days}j {hours}h"

    def _fmt(self, size_bytes: int) -> str:
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size_bytes < 1024: return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} PB"
