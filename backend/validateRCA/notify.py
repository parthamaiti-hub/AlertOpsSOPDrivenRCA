import logging

logger = logging.getLogger(__name__)


def notify_teams(alert_id: str, rca_summary: str, channel: str = "ops-team"):
    """Placeholder for Teams webhook notification."""
    logger.info("NOTIFY [%s] Alert %s: %s", channel, alert_id, rca_summary[:200])
