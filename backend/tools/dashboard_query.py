import logging
import random

logger = logging.getLogger(__name__)


def dashboard_query(dashboard: str = "", panels: list = None, time_range: str = "1h", **kwargs) -> dict:
    """Stub dashboard query tool. Returns mock panel data."""
    logger.info("dashboard_query stub: dashboard=%s panels=%s", dashboard, panels)
    panel_results = {}
    for panel in (panels or ["default"]):
        panel_results[panel] = {
            "status": "ok",
            "value": round(random.uniform(0.5, 95.0), 2),
            "unit": "%",
        }
    return {
        "tool": "dashboard_query",
        "dashboard": dashboard,
        "time_range": time_range,
        "status": "success",
        "panels": panel_results,
    }
