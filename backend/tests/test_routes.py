import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient, ASGITransport

from backend.main import app


@pytest.fixture
def mock_db():
    with patch("backend.routes.alerts.alerts_col") as mock_alerts, \
         patch("backend.routes.alerts.publish") as mock_publish:
        col = MagicMock()
        mock_alerts.return_value = col
        yield {"alerts_col": col, "publish": mock_publish}


@pytest.mark.asyncio
async def test_health():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_create_alert(mock_db):
    mock_result = MagicMock()
    mock_result.inserted_id = "abc123"
    mock_db["alerts_col"].insert_one = AsyncMock(return_value=mock_result)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/alerts", json={
            "source_application": "test-app",
            "domain": "infrastructure",
            "category": "performance",
            "severity": "critical",
        })
        assert resp.status_code == 201
        assert "alert_id" in resp.json()

    insert_doc = mock_db["alerts_col"].insert_one.call_args[0][0]
    assert insert_doc["source_type"] == "api"
    assert insert_doc["source_ref"].endswith("/api/alerts")
    assert insert_doc.get("logged_at") is not None


@pytest.mark.asyncio
async def test_create_text_alert_file_source(mock_db):
    mock_result = MagicMock()
    mock_result.inserted_id = "txt123"
    mock_db["alerts_col"].insert_one = AsyncMock(return_value=mock_result)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/alerts/text",
            json={
                "alert_text": "Disk usage above threshold",
                "raw_payload": {"filename": "disk_space_text_alert.txt"},
            },
        )
        assert resp.status_code == 201
        assert "alert_id" in resp.json()

    insert_doc = mock_db["alerts_col"].insert_one.call_args[0][0]
    assert insert_doc["source_type"] == "file"
    assert insert_doc["source_ref"] == "disk_space_text_alert.txt"
    assert insert_doc.get("logged_at") is not None
