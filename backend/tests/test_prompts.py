import pathlib

import pytest
import yaml


def test_file_prompt_loader_reads_yaml(tmp_path):
    from backend.prompts.loader import FilePromptLoader
    import backend.prompts.loader as mod

    yaml_file = tmp_path / "test_agent.yaml"
    yaml_file.write_text(yaml.dump({"greet": "Hello {name}, welcome to {place}"}))

    loader = FilePromptLoader()
    original = mod.PROMPTS_DIR
    mod.PROMPTS_DIR = tmp_path
    try:
        result = loader.get_prompt("test_agent", "greet")
        assert "Hello {name}" in result
        rendered = result.format_map({"name": "Alice", "place": "Wonderland"})
        assert rendered == "Hello Alice, welcome to Wonderland"
    finally:
        mod.PROMPTS_DIR = original


def test_file_prompt_loader_missing_file():
    from backend.prompts.loader import FilePromptLoader
    import backend.prompts.loader as mod

    original = mod.PROMPTS_DIR
    mod.PROMPTS_DIR = pathlib.Path("/nonexistent")
    try:
        loader = FilePromptLoader()
        with pytest.raises(FileNotFoundError):
            loader.get_prompt("missing_agent", "key")
    finally:
        mod.PROMPTS_DIR = original


def test_file_prompt_loader_missing_key(tmp_path):
    from backend.prompts.loader import FilePromptLoader
    import backend.prompts.loader as mod

    yaml_file = tmp_path / "agent.yaml"
    yaml_file.write_text(yaml.dump({"existing_key": "value"}))
    original = mod.PROMPTS_DIR
    mod.PROMPTS_DIR = tmp_path
    try:
        loader = FilePromptLoader()
        with pytest.raises(KeyError):
            loader.get_prompt("agent", "nonexistent_key")
    finally:
        mod.PROMPTS_DIR = original


def test_yaml_prompt_files_exist():
    prompts_dir = pathlib.Path(__file__).parent.parent.parent / "data" / "prompts"
    expected = ["identify_sop.yaml", "execute_sop.yaml", "validate_rca.yaml"]
    for name in expected:
        path = prompts_dir / name
        assert path.exists(), f"Missing prompt file: {path}"
        with open(path) as f:
            data = yaml.safe_load(f)
        assert data, f"Empty prompt file: {path}"


def test_identify_sop_prompt_substitution():
    prompts_dir = pathlib.Path(__file__).parent.parent.parent / "data" / "prompts"
    with open(prompts_dir / "identify_sop.yaml") as f:
        data = yaml.safe_load(f)
    prompt = data["select_sop"].format_map({
        "application": "MyApp",
        "domain": "infra",
        "category": "memory",
        "severity": "high",
        "sop_keys": ["memory_leak"],
        "dynamic_fields": '{"environment": "production"}',
        "match_info": '[{"sop_id": "sop1"}]',
    })
    assert "MyApp" in prompt
    assert "memory" in prompt


def test_execute_sop_prompt_substitution():
    prompts_dir = pathlib.Path(__file__).parent.parent.parent / "data" / "prompts"
    with open(prompts_dir / "execute_sop.yaml") as f:
        data = yaml.safe_load(f)
    prompt = data["generate_rca"].format_map({
        "source_application": "App1",
        "domain": "infra",
        "category": "cpu",
        "severity": "critical",
        "raw_payload": '{"host": "srv1"}',
        "results_summary": "[]",
    })
    assert "App1" in prompt
    assert "root_cause" in prompt


def test_validate_rca_prompt_substitution():
    prompts_dir = pathlib.Path(__file__).parent.parent.parent / "data" / "prompts"
    with open(prompts_dir / "validate_rca.yaml") as f:
        data = yaml.safe_load(f)
    prompt = data["validate"].format_map({
        "root_cause": "memory leak",
        "impact": "service degradation",
        "recommendation": "restart service",
        "similar_summary": "[]",
    })
    assert "memory leak" in prompt
    assert "confidence_score" in prompt


def test_get_loader_returns_file_by_default():
    from backend.prompts.loader import FilePromptLoader
    import backend.prompts.loader as mod

    mod._loader = None
    from backend.config.settings import settings
    original = settings.prompt_backend
    settings.prompt_backend = "file"
    try:
        loader = mod.get_loader()
        assert isinstance(loader, FilePromptLoader)
    finally:
        settings.prompt_backend = original
        mod._loader = None


def test_get_loader_returns_db_when_configured():
    from backend.prompts.loader import DBPromptLoader
    import backend.prompts.loader as mod

    mod._loader = None
    from backend.config.settings import settings
    original = settings.prompt_backend
    settings.prompt_backend = "db"
    try:
        loader = mod.get_loader()
        assert isinstance(loader, DBPromptLoader)
    finally:
        settings.prompt_backend = original
        mod._loader = None
