import logging

logger = logging.getLogger(__name__)


def teams_message(
    channel: str = "",
    message: str = "",
    thread: str = "",
    tag: list = None,
    include: list = None,
    ack: bool = False,
    template: str = "",
    **kwargs,
) -> dict:
    logger.info("teams_message stub: channel=%s message=%s", channel, message or template)
    return {
        "tool": "teams_message",
        "channel": channel,
        "status": "sent",
        "ack": ack,
    }
