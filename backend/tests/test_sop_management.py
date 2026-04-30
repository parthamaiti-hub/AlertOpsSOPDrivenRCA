import json
import pathlib
from unittest.mock import MagicMock, patch

import pytest

from backend.models.schemas import SOPMapping
from backend.sopmanagement.service import load_mappings


DATA_DIR = pathlib.Path(__file__).parent.parent.parent / "data"


def test_load_mappings_returns_dict():
    mappings = load_mappings()
    assert isinstance(mappings, dict)
    assert len(mappings) > 0


def test_load_mappings_has_required_fields():
    mappings = load_mappings()
    for filename, meta in mappings.items():
        assert "name" in meta
        assert "application" in meta
        assert "domain" in meta
        assert "category" in meta
        assert "severity" in meta
        assert "workflow_file" in meta


def test_load_mappings_workflow_files_exist():
    mappings = load_mappings()
    for filename, meta in mappings.items():
        doc_path = DATA_DIR / "sop_documents" / filename
        wf_path = DATA_DIR / "sop_workflows" / meta["workflow_file"]
        assert doc_path.exists(), f"Missing SOP doc: {doc_path}"
        assert wf_path.exists(), f"Missing workflow: {wf_path}"


def test_sop_mapping_schema():
    m = SOPMapping(
        sop_document_file="high_cpu_alert.txt",
        workflow_file="high_cpu_workflow.json",
        sop_id="SOP_HIGH_CPU",
        name="High CPU Alert",
        application="order-service",
        domain="infrastructure",
        category="performance",
        severity="critical",
    )
    assert m.sop_id == "SOP_HIGH_CPU"
    assert m.seeded is False
    assert m.sop_document_id is None
    assert m.workflow_id is None


def test_sop_mapping_schema_with_ids():
    m = SOPMapping(
        sop_document_file="db_connection_pool.txt",
        workflow_file="db_connection_pool_workflow.json",
        sop_id="SOP_DB_CONN_POOL",
        name="DB Connection Pool",
        application="payment-gateway",
        domain="database",
        category="connectivity",
        severity="high",
        sop_document_id="abc123",
        workflow_id="def456",
        seeded=True,
    )
    assert m.seeded is True
    assert m.sop_document_id == "abc123"


def test_seed_all_calls_insert_and_index():
    mock_db = MagicMock()
    mock_mappings_col = MagicMock()
    mock_docs_col = MagicMock()
    mock_wf_col = MagicMock()

    mock_mappings_col.find_one.return_value = None  # nothing pre-existing
    mock_docs_col.insert_one.return_value = MagicMock(inserted_id="docid1")
    mock_wf_col.insert_one.return_value = MagicMock(inserted_id="wfid1")

    def db_getitem(key):
        return {"sop_documents": mock_docs_col, "sop_workflows": mock_wf_col, "sop_mappings": mock_mappings_col}[key]

    mock_db.__getitem__ = MagicMock(side_effect=db_getitem)

    with patch("backend.sopmanagement.service.get_sync_db", return_value=mock_db), \
         patch("backend.sopmanagement.service.index_sop_document") as mock_index:
        from backend.sopmanagement.service import seed_all
        results = seed_all()

    assert len(results) == 4
    assert all(r["status"] == "seeded" for r in results)
    assert mock_index.call_count == 4
    assert mock_mappings_col.insert_one.call_count == 4


def test_seed_all_skips_existing():
    import json, pathlib
    mapping_file = pathlib.Path(__file__).parent.parent.parent / "data" / "sop_mappingdata.json"
    mappings = json.loads(mapping_file.read_text())
    # Build mock records that match current file data (including dynamic_classifiers)
    def make_existing(filename, meta):
        return {
            "sop_document_file": filename,
            "sop_id": meta.get("sop_id", ""),
            "dynamic_classifiers": meta.get("dynamic_classifiers", []),
        }

    mock_db = MagicMock()
    mock_mappings_col = MagicMock()
    mock_mappings_col.find_one.side_effect = lambda q: make_existing(
        q["sop_document_file"],
        mappings.get(q["sop_document_file"], {}),
    ) if q.get("sop_document_file") in mappings else None

    mock_db.__getitem__ = MagicMock(return_value=mock_mappings_col)

    with patch("backend.sopmanagement.service.get_sync_db", return_value=mock_db), \
         patch("backend.sopmanagement.service.index_sop_document") as mock_index, \
         patch("backend.sopmanagement.service.is_sop_indexed", return_value=True):
        from backend.sopmanagement.service import seed_all
        results = seed_all()

    assert all(r["status"] == "skipped" for r in results)
    mock_index.assert_not_called()


def test_get_all_mappings():
    mock_db = MagicMock()
    mock_col = MagicMock()
    mock_col.find.return_value = [{"sop_id": "SOP_HIGH_CPU"}, {"sop_id": "SOP_DB_CONN_POOL"}]
    mock_db.__getitem__ = MagicMock(return_value=mock_col)

    with patch("backend.sopmanagement.service.get_sync_db", return_value=mock_db):
        from backend.sopmanagement.service import get_all_mappings
        result = get_all_mappings()

    assert len(result) == 2
    assert result[0]["sop_id"] == "SOP_HIGH_CPU"


def test_get_mapping_by_sop_id_found():
    mock_db = MagicMock()
    mock_col = MagicMock()
    mock_col.find_one.return_value = {"sop_id": "SOP_MEMORY_LEAK", "name": "Memory Leak Detection"}
    mock_db.__getitem__ = MagicMock(return_value=mock_col)

    with patch("backend.sopmanagement.service.get_sync_db", return_value=mock_db):
        from backend.sopmanagement.service import get_mapping_by_sop_id
        result = get_mapping_by_sop_id("SOP_MEMORY_LEAK")

    assert result["sop_id"] == "SOP_MEMORY_LEAK"


def test_get_mapping_by_sop_id_not_found():
    mock_db = MagicMock()
    mock_col = MagicMock()
    mock_col.find_one.return_value = None
    mock_db.__getitem__ = MagicMock(return_value=mock_col)

    with patch("backend.sopmanagement.service.get_sync_db", return_value=mock_db):
        from backend.sopmanagement.service import get_mapping_by_sop_id
        result = get_mapping_by_sop_id("SOP_DOES_NOT_EXIST")

    assert result is None


# ──────────────────────────────────────────────────────────────
# Tests for new service functions (create / update / workflow)
# ──────────────────────────────────────────────────────────────

def _make_mock_db(docs_col, wf_col, mappings_col):
    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(
        side_effect=lambda k: {
            "sop_documents": docs_col,
            "sop_workflows": wf_col,
            "sop_mappings": mappings_col,
        }[k]
    )
    return mock_db


def test_create_sop_mapping_success():
    mock_docs = MagicMock()
    mock_wf = MagicMock()
    mock_mappings = MagicMock()

    mock_mappings.find_one.return_value = None  # not duplicate
    mock_docs.insert_one.return_value = MagicMock(inserted_id="docid_new")
    mock_wf.insert_one.return_value = MagicMock(inserted_id="wfid_new")

    mock_db = _make_mock_db(mock_docs, mock_wf, mock_mappings)

    with patch("backend.sopmanagement.service.get_sync_db", return_value=mock_db), \
         patch("backend.sopmanagement.service.index_sop_document") as mock_index:
        from backend.sopmanagement.service import create_sop_mapping
        result = create_sop_mapping(
            sop_id="SOP_NEW_TEST",
            name="New Test SOP",
            application="test-app",
            domain="test-domain",
            category="test-cat",
            severity="high",
            doc_content="SOP document content",
            doc_filename="test_doc.txt",
            workflow_data={"steps": []},
            workflow_filename="test_workflow.json",
        )

    assert result["sop_id"] == "SOP_NEW_TEST"
    assert result["status"] == "created"
    mock_index.assert_called_once()
    # sop_id override should be applied
    inserted_wf = mock_wf.insert_one.call_args[0][0]
    assert inserted_wf["sop_id"] == "SOP_NEW_TEST"


def test_create_sop_mapping_duplicate_raises():
    mock_docs = MagicMock()
    mock_wf = MagicMock()
    mock_mappings = MagicMock()
    mock_mappings.find_one.return_value = {"sop_id": "SOP_EXISTING"}  # already exists

    mock_db = _make_mock_db(mock_docs, mock_wf, mock_mappings)

    with patch("backend.sopmanagement.service.get_sync_db", return_value=mock_db), \
         patch("backend.sopmanagement.service.index_sop_document"):
        from backend.sopmanagement.service import create_sop_mapping
        with pytest.raises(ValueError, match="already exists"):
            create_sop_mapping(
                sop_id="SOP_EXISTING",
                name="n", application="a", domain="d", category="c", severity="s",
                doc_content="x", doc_filename="x.txt",
                workflow_data={}, workflow_filename="w.json",
            )


def test_update_classifier_updates_all():
    mock_docs = MagicMock()
    mock_wf = MagicMock()
    mock_mappings = MagicMock()

    existing_mapping = {
        "sop_id": "SOP_HIGH_CPU",
        "sop_document_id": "507f1f77bcf86cd799439011",
        "name": "Old Name",
        "application": "old-app",
        "domain": "old-domain",
        "category": "old-cat",
        "severity": "low",
    }
    mock_mappings.find_one.return_value = existing_mapping
    updated_mapping = {**existing_mapping, "name": "New Name", "application": "new-app"}
    mock_mappings.find_one_and_update = MagicMock(return_value=updated_mapping)

    mock_docs.update_one = MagicMock()
    mock_db = _make_mock_db(mock_docs, mock_wf, mock_mappings)

    with patch("backend.sopmanagement.service.get_sync_db", return_value=mock_db), \
         patch("backend.sopmanagement.service.index_sop_document") as mock_index:
        from backend.sopmanagement.service import update_classifier
        result = update_classifier("SOP_HIGH_CPU", {"name": "New Name", "application": "new-app"})

    mock_docs.update_one.assert_called_once()
    mock_index.assert_called_once()
    assert result is not None


def test_update_classifier_not_found_raises():
    mock_docs = MagicMock()
    mock_wf = MagicMock()
    mock_mappings = MagicMock()
    mock_mappings.find_one.return_value = None

    mock_db = _make_mock_db(mock_docs, mock_wf, mock_mappings)

    with patch("backend.sopmanagement.service.get_sync_db", return_value=mock_db), \
         patch("backend.sopmanagement.service.index_sop_document"):
        from backend.sopmanagement.service import update_classifier
        with pytest.raises(ValueError, match="not found"):
            update_classifier("SOP_MISSING", {"name": "x"})


def test_get_workflow_by_sop_id_found():
    mock_docs = MagicMock()
    mock_wf = MagicMock()
    mock_mappings = MagicMock()
    mock_wf.find_one.return_value = {"sop_id": "SOP_HIGH_CPU", "triaging_steps": []}

    mock_db = _make_mock_db(mock_docs, mock_wf, mock_mappings)

    with patch("backend.sopmanagement.service.get_sync_db", return_value=mock_db):
        from backend.sopmanagement.service import get_workflow_by_sop_id
        result = get_workflow_by_sop_id("SOP_HIGH_CPU")

    assert result["sop_id"] == "SOP_HIGH_CPU"


def test_get_workflow_by_sop_id_not_found():
    mock_docs = MagicMock()
    mock_wf = MagicMock()
    mock_mappings = MagicMock()
    mock_wf.find_one.return_value = None

    mock_db = _make_mock_db(mock_docs, mock_wf, mock_mappings)

    with patch("backend.sopmanagement.service.get_sync_db", return_value=mock_db):
        from backend.sopmanagement.service import get_workflow_by_sop_id
        result = get_workflow_by_sop_id("SOP_MISSING")

    assert result is None


def test_update_workflow_success():
    mock_docs = MagicMock()
    mock_wf = MagicMock()
    mock_mappings = MagicMock()
    mock_wf.find_one.return_value = {"_id": "wfid123", "sop_id": "SOP_HIGH_CPU"}
    mock_wf.replace_one = MagicMock()

    mock_db = _make_mock_db(mock_docs, mock_wf, mock_mappings)

    with patch("backend.sopmanagement.service.get_sync_db", return_value=mock_db):
        from backend.sopmanagement.service import update_workflow
        update_workflow("SOP_HIGH_CPU", {"sop_id": "SOP_HIGH_CPU", "steps": [{"id": 1}]})

    mock_wf.replace_one.assert_called_once()


def test_update_workflow_not_found_raises():
    mock_docs = MagicMock()
    mock_wf = MagicMock()
    mock_mappings = MagicMock()
    mock_wf.find_one.return_value = None

    mock_db = _make_mock_db(mock_docs, mock_wf, mock_mappings)

    with patch("backend.sopmanagement.service.get_sync_db", return_value=mock_db):
        from backend.sopmanagement.service import update_workflow
        with pytest.raises(ValueError, match="not found"):
            update_workflow("SOP_MISSING", {"steps": []})


def test_update_doc_file_success():
    mock_docs = MagicMock()
    mock_wf = MagicMock()
    mock_mappings = MagicMock()

    valid_doc_id = "507f1f77bcf86cd799439011"
    mapping = {"sop_id": "SOP_HIGH_CPU", "sop_document_id": valid_doc_id,
               "application": "a", "domain": "d", "category": "c", "severity": "s"}
    mock_mappings.find_one.return_value = mapping
    mock_docs.update_one = MagicMock()

    mock_db = _make_mock_db(mock_docs, mock_wf, mock_mappings)

    with patch("backend.sopmanagement.service.get_sync_db", return_value=mock_db), \
         patch("backend.sopmanagement.service.index_sop_document") as mock_index:
        from backend.sopmanagement.service import update_doc_file
        update_doc_file("SOP_HIGH_CPU", "new content here", "new_doc.txt")

    mock_docs.update_one.assert_called_once()
    mock_index.assert_called_once_with(
        "SOP_HIGH_CPU",
        "new content here",
        {"application": "a", "domain": "d", "category": "c", "severity": "s", "sop_document_id": valid_doc_id},
    )


def test_update_doc_file_not_found_raises():
    mock_docs = MagicMock()
    mock_wf = MagicMock()
    mock_mappings = MagicMock()
    mock_mappings.find_one.return_value = None

    mock_db = _make_mock_db(mock_docs, mock_wf, mock_mappings)

    with patch("backend.sopmanagement.service.get_sync_db", return_value=mock_db), \
         patch("backend.sopmanagement.service.index_sop_document"):
        from backend.sopmanagement.service import update_doc_file
        with pytest.raises(ValueError, match="not found"):
            update_doc_file("SOP_MISSING", "content", "doc.txt")
