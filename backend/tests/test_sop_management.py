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
        return {"sop_documents": mock_docs_col, "sop_workflows": mock_wf_col, "sop_mappings": mock_mappings_col, "sop_mapping_history": MagicMock()}[key]

    mock_db.__getitem__ = MagicMock(side_effect=db_getitem)

    with patch("backend.sopmanagement.service.get_sync_db", return_value=mock_db), \
         patch("backend.sopmanagement.service.index_sop_document") as mock_index:
        from backend.sopmanagement.service import seed_all
        results = seed_all()

    assert len(results) == 5
    assert all(r["status"] == "seeded" for r in results)
    assert mock_index.call_count == 5
    assert mock_mappings_col.insert_one.call_count == 5


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
    # get_mapping_by_sop_id delegates to get_active_mapping which uses find()
    mock_col.find.return_value = [{"_id": "507f1f77bcf86cd799439011", "sop_id": "SOP_MEMORY_LEAK", "name": "Memory Leak Detection", "sop_document_version": "1.0", "workflow_version": "1.0"}]
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
    history_col = MagicMock()
    mock_db.__getitem__ = MagicMock(
        side_effect=lambda k: {
            "sop_documents": docs_col,
            "sop_workflows": wf_col,
            "sop_mappings": mappings_col,
            "sop_mapping_history": history_col,
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

    valid_id = "507f1f77bcf86cd799439011"
    active = {
        "_id": valid_id,
        "sop_id": "SOP_HIGH_CPU",
        "workflow_id": valid_id,
        "sop_document_version": "1.0",
        "workflow_version": "1.0",
    }
    mock_mappings.find.return_value = [active]
    mock_wf.find_one.return_value = {"_id": MagicMock(__str__=lambda s: valid_id), "sop_id": "SOP_HIGH_CPU", "triaging_steps": []}

    mock_db = _make_mock_db(mock_docs, mock_wf, mock_mappings)

    with patch("backend.sopmanagement.service.get_sync_db", return_value=mock_db):
        from backend.sopmanagement.service import get_workflow_by_sop_id
        result = get_workflow_by_sop_id("SOP_HIGH_CPU")

    assert result["sop_id"] == "SOP_HIGH_CPU"


def test_get_workflow_by_sop_id_not_found():
    mock_docs = MagicMock()
    mock_wf = MagicMock()
    mock_mappings = MagicMock()
    mock_mappings.find.return_value = []  # no mappings → get_active_mapping returns None

    mock_db = _make_mock_db(mock_docs, mock_wf, mock_mappings)

    with patch("backend.sopmanagement.service.get_sync_db", return_value=mock_db):
        from backend.sopmanagement.service import get_workflow_by_sop_id
        result = get_workflow_by_sop_id("SOP_MISSING")

    assert result is None


def test_update_workflow_success():
    valid_id = "507f1f77bcf86cd799439011"
    active = {
        "_id": valid_id,
        "sop_id": "SOP_HIGH_CPU",
        "workflow_id": valid_id,
        "sop_document_version": "1.0",
        "workflow_version": "1.0",
    }

    mock_docs = MagicMock()
    mock_wf = MagicMock()
    mock_mappings = MagicMock()
    mock_mappings.find.return_value = [active]
    mock_wf.insert_one.return_value = MagicMock(inserted_id="newwfid")

    mock_db = _make_mock_db(mock_docs, mock_wf, mock_mappings)

    with patch("backend.sopmanagement.service.get_sync_db", return_value=mock_db):
        from backend.sopmanagement.service import update_workflow
        new_version = update_workflow("SOP_HIGH_CPU", {"sop_id": "SOP_HIGH_CPU", "steps": []})

    assert new_version == "1.1"
    mock_wf.insert_one.assert_called_once()
    mock_mappings.update_one.assert_called_once()


def test_update_workflow_not_found_raises():
    mock_docs = MagicMock()
    mock_wf = MagicMock()
    mock_mappings = MagicMock()
    mock_mappings.find.return_value = []  # no mappings → get_active_mapping returns None

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


# ──────────────────────────────────────────────────────────────
# version_utils tests
# ──────────────────────────────────────────────────────────────

def test_validate_version_format_valid():
    from backend.sopmanagement.version_utils import validate_version_format
    assert validate_version_format("1.0") is True
    assert validate_version_format("1.2") is True
    assert validate_version_format("10.99") is True


def test_validate_version_format_invalid():
    from backend.sopmanagement.version_utils import validate_version_format
    assert validate_version_format("1") is False
    assert validate_version_format("abc") is False
    assert validate_version_format("1.2.3") is False
    assert validate_version_format("") is False
    assert validate_version_format("1.") is False


def test_get_next_valid_versions():
    from backend.sopmanagement.version_utils import get_next_valid_versions
    assert get_next_valid_versions("1.2") == ("1.3", "2.0")
    assert get_next_valid_versions("1.0") == ("1.1", "2.0")
    assert get_next_valid_versions("3.9") == ("3.10", "4.0")


def test_is_valid_progression_minor_bump():
    from backend.sopmanagement.version_utils import is_valid_progression
    assert is_valid_progression("1.2", "1.3") is True


def test_is_valid_progression_major_bump():
    from backend.sopmanagement.version_utils import is_valid_progression
    assert is_valid_progression("1.2", "2.0") is True


def test_is_valid_progression_skips_minor():
    from backend.sopmanagement.version_utils import is_valid_progression
    assert is_valid_progression("1.2", "1.4") is False


def test_is_valid_progression_lower_version():
    from backend.sopmanagement.version_utils import is_valid_progression
    assert is_valid_progression("1.2", "0.9") is False


def test_is_valid_progression_same_version():
    from backend.sopmanagement.version_utils import is_valid_progression
    assert is_valid_progression("1.2", "1.2") is False


def test_is_valid_progression_major_non_zero_minor():
    from backend.sopmanagement.version_utils import is_valid_progression
    assert is_valid_progression("1.0", "2.1") is False


# ──────────────────────────────────────────────────────────────
# get_active_mapping tests
# ──────────────────────────────────────────────────────────────

def _mock_db_with_mappings(mapping_list):
    mock_db = MagicMock()
    mock_col = MagicMock()
    mock_col.find.return_value = mapping_list
    mock_db.__getitem__ = MagicMock(return_value=mock_col)
    return mock_db


def test_get_active_mapping_returns_highest_version():
    mappings = [
        {"_id": "id1", "sop_id": "SOP_X", "sop_document_version": "1.0", "workflow_version": "1.0"},
        {"_id": "id2", "sop_id": "SOP_X", "sop_document_version": "1.2", "workflow_version": "1.2"},
        {"_id": "id3", "sop_id": "SOP_X", "sop_document_version": "1.1", "workflow_version": "1.1"},
    ]
    mock_db = _mock_db_with_mappings(mappings)
    with patch("backend.sopmanagement.service.get_sync_db", return_value=mock_db):
        from backend.sopmanagement.service import get_active_mapping
        result = get_active_mapping("SOP_X")
    assert result["sop_document_version"] == "1.2"


def test_get_active_mapping_single():
    mappings = [
        {"_id": "id1", "sop_id": "SOP_X", "sop_document_version": "1.0", "workflow_version": "1.0"},
    ]
    mock_db = _mock_db_with_mappings(mappings)
    with patch("backend.sopmanagement.service.get_sync_db", return_value=mock_db):
        from backend.sopmanagement.service import get_active_mapping
        result = get_active_mapping("SOP_X")
    assert result["sop_document_version"] == "1.0"


def test_get_active_mapping_none_when_missing():
    mock_db = _mock_db_with_mappings([])
    with patch("backend.sopmanagement.service.get_sync_db", return_value=mock_db):
        from backend.sopmanagement.service import get_active_mapping
        result = get_active_mapping("SOP_MISSING")
    assert result is None


# ──────────────────────────────────────────────────────────────
# create_sop_mapping version field tests
# ──────────────────────────────────────────────────────────────

def test_create_sop_mapping_stores_version_fields():
    mock_docs = MagicMock()
    mock_wf = MagicMock()
    mock_mappings = MagicMock()

    mock_mappings.find_one.return_value = None
    mock_mappings.find.return_value = []
    mock_docs.insert_one.return_value = MagicMock(inserted_id="docid")
    mock_wf.insert_one.return_value = MagicMock(inserted_id="wfid")

    mock_db = _make_mock_db(mock_docs, mock_wf, mock_mappings)

    with patch("backend.sopmanagement.service.get_sync_db", return_value=mock_db), \
         patch("backend.sopmanagement.service.index_sop_document"):
        from backend.sopmanagement.service import create_sop_mapping
        result = create_sop_mapping(
            sop_id="SOP_V_TEST",
            name="V Test",
            application="app",
            domain="dom",
            category="cat",
            severity="high",
            doc_content="content",
            doc_filename="doc.txt",
            workflow_data={},
            workflow_filename="wf.json",
            sop_document_version="1.0",
            workflow_version="1.0",
        )

    assert result["sop_document_version"] == "1.0"
    assert result["workflow_version"] == "1.0"
    inserted = mock_mappings.insert_one.call_args[0][0]
    assert inserted["sop_document_version"] == "1.0"
    assert inserted["workflow_version"] == "1.0"
    assert inserted["change_type"] == "new_sop"


def test_create_sop_mapping_invalid_version_raises():
    with patch("backend.sopmanagement.service.get_sync_db"):
        from backend.sopmanagement.service import create_sop_mapping
        with pytest.raises(ValueError, match="Invalid sop_document_version"):
            create_sop_mapping(
                sop_id="SOP_X", name="x", application="a", domain="d",
                category="c", severity="s", doc_content="x", doc_filename="x.txt",
                workflow_data={}, workflow_filename="x.json",
                sop_document_version="bad", workflow_version="1.0",
            )


# ──────────────────────────────────────────────────────────────
# create_sop_version tests
# ──────────────────────────────────────────────────────────────

def _active_v10():
    return {
        "_id": "507f1f77bcf86cd799439011",
        "sop_id": "SOP_X",
        "name": "Test SOP",
        "application": "app",
        "domain": "dom",
        "category": "cat",
        "severity": "high",
        "dynamic_classifiers": [],
        "sop_document_version": "1.0",
        "workflow_version": "1.0",
        "workflow_id": "507f1f77bcf86cd799439022",
        "source": "ui",
    }


def test_create_sop_version_success():
    active = _active_v10()
    mock_docs = MagicMock()
    mock_wf = MagicMock()
    mock_mappings = MagicMock()
    # get_active_mapping uses find()
    mock_mappings.find.return_value = [active]
    mock_docs.insert_one.return_value = MagicMock(inserted_id="newdocid")
    mock_wf.insert_one.return_value = MagicMock(inserted_id="newwfid")
    mock_history = MagicMock()

    def db_getitem(key):
        return {
            "sop_documents": mock_docs,
            "sop_workflows": mock_wf,
            "sop_mappings": mock_mappings,
            "sop_mapping_history": mock_history,
        }[key]

    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(side_effect=db_getitem)

    with patch("backend.sopmanagement.service.get_sync_db", return_value=mock_db), \
         patch("backend.sopmanagement.service.index_sop_document"):
        from backend.sopmanagement.service import create_sop_version
        result = create_sop_version(
            sop_id="SOP_X",
            doc_content="new content",
            doc_filename="doc_v2.txt",
            workflow_data={"sop_id": "SOP_X"},
            workflow_filename="wf_v2.json",
            sop_document_version="1.1",
            workflow_version="1.1",
        )

    assert result["sop_document_version"] == "1.1"
    assert result["workflow_version"] == "1.1"
    assert result["status"] == "new_version_created"
    mock_history.insert_one.assert_called_once()
    archive_call = mock_history.insert_one.call_args[0][0]
    assert archive_call["change_type"] == "new_version"
    assert archive_call["sop_document_version"] == "1.0"


def test_create_sop_version_invalid_progression_raises():
    active = _active_v10()
    mock_mappings = MagicMock()
    mock_mappings.find.return_value = [active]
    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_mappings)

    with patch("backend.sopmanagement.service.get_sync_db", return_value=mock_db):
        from backend.sopmanagement.service import create_sop_version
        with pytest.raises(ValueError, match="only 1.1 or 2.0 are allowed"):
            create_sop_version(
                sop_id="SOP_X",
                doc_content="c",
                doc_filename="d.txt",
                workflow_data={},
                workflow_filename="w.json",
                sop_document_version="1.3",  # skip — invalid
                workflow_version="1.1",
            )


def test_create_sop_version_sop_not_found_raises():
    mock_mappings = MagicMock()
    mock_mappings.find.return_value = []
    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_mappings)

    with patch("backend.sopmanagement.service.get_sync_db", return_value=mock_db):
        from backend.sopmanagement.service import create_sop_version
        with pytest.raises(ValueError, match="not found"):
            create_sop_version(
                sop_id="SOP_GHOST",
                doc_content="c",
                doc_filename="d.txt",
                workflow_data={},
                workflow_filename="w.json",
                sop_document_version="1.1",
                workflow_version="1.1",
            )


# ──────────────────────────────────────────────────────────────
# update_workflow version bump tests
# ──────────────────────────────────────────────────────────────

def test_update_workflow_bumps_minor_version():
    valid_id = "507f1f77bcf86cd799439011"
    active = {
        "_id": valid_id,
        "sop_id": "SOP_HIGH_CPU",
        "workflow_id": valid_id,
        "sop_document_version": "1.2",
        "workflow_version": "1.2",
    }
    mock_docs = MagicMock()
    mock_wf = MagicMock()
    mock_mappings = MagicMock()
    mock_history = MagicMock()
    mock_mappings.find.return_value = [active]
    mock_wf.insert_one.return_value = MagicMock(inserted_id="newwfid")

    def db_getitem(key):
        return {
            "sop_documents": mock_docs,
            "sop_workflows": mock_wf,
            "sop_mappings": mock_mappings,
            "sop_mapping_history": mock_history,
        }[key]

    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(side_effect=db_getitem)

    with patch("backend.sopmanagement.service.get_sync_db", return_value=mock_db):
        from backend.sopmanagement.service import update_workflow
        new_v = update_workflow("SOP_HIGH_CPU", {"sop_id": "SOP_HIGH_CPU", "triaging_steps": []})

    assert new_v == "1.3"
    mock_history.insert_one.assert_called_once()
    archive_call = mock_history.insert_one.call_args[0][0]
    assert archive_call["change_type"] == "workflow_edit"
    assert archive_call["workflow_version"] == "1.2"
