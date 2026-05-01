import logging

logger = logging.getLogger(__name__)


def servicenow_incident(
    priority: str = "",
    assignment_group: str = "",
    description: str = "",
    template: str = "",
    **kwargs,
) -> dict:
    logger.info(
        "servicenow_incident stub: priority=%s assignment_group=%s",
        priority,
        assignment_group,
    )
    return {
        "tool": "servicenow_incident",
        "status": "created",
        "priority": priority,
        "assignment_group": assignment_group,
        "template": template,
    }
