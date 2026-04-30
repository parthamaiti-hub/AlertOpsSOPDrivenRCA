from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

from backend.config.settings import settings

_client: Optional[AsyncIOMotorClient] = None
_sync_client: Optional[MongoClient] = None


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(settings.mongodb_uri)
    return _client


def get_sync_client() -> MongoClient:
    global _sync_client
    if _sync_client is None:
        _sync_client = MongoClient(settings.mongodb_uri)
    return _sync_client


def get_db():
    return get_client()[settings.mongodb_db]


def get_sync_db():
    return get_sync_client()[settings.mongodb_db]


def alerts_col():
    return get_db()["alerts"]


def sop_documents_col():
    return get_db()["sop_documents"]


def sop_workflows_col():
    return get_db()["sop_workflows"]


def rca_results_col():
    return get_db()["rca_results"]


def validation_results_col():
    return get_db()["validation_results"]


def feedback_col():
    return get_db()["feedback"]


# Sync accessors for worker processes (non-async context)
def alerts_col_sync():
    return get_sync_db()["alerts"]


def sop_workflows_col_sync():
    return get_sync_db()["sop_workflows"]


def rca_results_col_sync():
    return get_sync_db()["rca_results"]


def validation_results_col_sync():
    return get_sync_db()["validation_results"]


def sop_mappings_col():
    return get_db()["sop_mappings"]


def sop_mappings_col_sync():
    return get_sync_db()["sop_mappings"]


def prompts_col():
    return get_db()["prompts"]


def prompts_col_sync():
    return get_sync_db()["prompts"]


def classifier_match_logs_col():
    return get_db()["classifier_match_logs"]


def classifier_match_logs_col_sync():
    return get_sync_db()["classifier_match_logs"]


def alert_retry_attempts_col():
    return get_db()["alert_retry_attempts"]


def alert_retry_attempts_col_sync():
    return get_sync_db()["alert_retry_attempts"]


def retry_stage_events_col():
    return get_db()["retry_stage_events"]


def retry_stage_events_col_sync():
    return get_sync_db()["retry_stage_events"]


def tools_col():
    return get_db()["tools"]


def tools_col_sync():
    return get_sync_db()["tools"]


def tools_history_col():
    return get_db()["tools_history"]


def tools_history_col_sync():
    return get_sync_db()["tools_history"]
