import logging

logger = logging.getLogger(__name__)


def page_team(team: str = "", context: list = None, **kwargs) -> dict:
    context_refs = context or []
    logger.info("page_team stub: paging team=%s context_refs=%s", team, context_refs)
    return {
        "tool": "page_team",
        "team": team,
        "status": "paged",
        "context_refs": context_refs,
    }
