import logging
import pathlib
from datetime import UTC, datetime

import yaml

logger = logging.getLogger(__name__)

PROMPTS_DIR = pathlib.Path(__file__).parent.parent.parent / "data" / "prompts"


def seed_prompts():
    from backend.models.database import prompts_col_sync

    col = prompts_col_sync()
    col.create_index([("agent", 1), ("key", 1)], unique=True)

    count = 0
    for yaml_file in sorted(PROMPTS_DIR.glob("*.yaml")):
        agent = yaml_file.stem
        with open(yaml_file, "r") as f:
            data = yaml.safe_load(f)
        if not data:
            continue
        for key, template in data.items():
            existing = col.find_one({"agent": agent, "key": key})
            if existing:
                continue
            col.insert_one({
                "agent": agent,
                "key": key,
                "template": template,
                "version": 1,
                "updated_at": datetime.now(UTC),
            })
            count += 1
            logger.info("Seeded prompt %s/%s", agent, key)
    logger.info("Prompt seeding complete: %d new prompts", count)
    return count
