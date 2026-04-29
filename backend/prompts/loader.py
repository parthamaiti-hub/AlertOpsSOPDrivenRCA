import logging
import pathlib
from abc import ABC, abstractmethod

import yaml

from backend.config.settings import settings

logger = logging.getLogger(__name__)

PROMPTS_DIR = pathlib.Path(__file__).parent.parent.parent / "data" / "prompts"


class PromptLoader(ABC):
    @abstractmethod
    def get_prompt(self, agent: str, key: str) -> str: ...


class FilePromptLoader(PromptLoader):
    def get_prompt(self, agent: str, key: str) -> str:
        path = PROMPTS_DIR / f"{agent}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"Prompt file not found: {path}")
        with open(path, "r") as f:
            data = yaml.safe_load(f)
        if key not in data:
            raise KeyError(f"Prompt key '{key}' not found in {path}")
        return data[key]


class DBPromptLoader(PromptLoader):
    def __init__(self):
        self._file_fallback = FilePromptLoader()

    def get_prompt(self, agent: str, key: str) -> str:
        try:
            from backend.models.database import prompts_col_sync

            doc = prompts_col_sync().find_one({"agent": agent, "key": key})
            if doc:
                return doc["template"]
        except Exception:
            logger.warning("Failed to read prompt from DB, falling back to file", exc_info=True)
        return self._file_fallback.get_prompt(agent, key)


_loader = None


def get_loader() -> PromptLoader:
    global _loader
    if _loader is None:
        if settings.prompt_backend == "db":
            _loader = DBPromptLoader()
        else:
            _loader = FilePromptLoader()
    return _loader
