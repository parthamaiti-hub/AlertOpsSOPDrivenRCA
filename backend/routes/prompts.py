import logging
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.models.database import prompts_col

router = APIRouter(prefix="/api/prompts", tags=["prompts"])
logger = logging.getLogger(__name__)


class PromptUpdate(BaseModel):
    template: str


@router.get("")
async def list_prompts():
    docs = await prompts_col().find({}, {"_id": 0}).to_list(100)
    return docs


@router.get("/{agent}/{key}")
async def get_prompt(agent: str, key: str):
    doc = await prompts_col().find_one({"agent": agent, "key": key}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Prompt {agent}/{key} not found")
    return doc


@router.put("/{agent}/{key}")
async def update_prompt(agent: str, key: str, body: PromptUpdate):
    result = await prompts_col().find_one({"agent": agent, "key": key})
    if not result:
        raise HTTPException(status_code=404, detail=f"Prompt {agent}/{key} not found")
    version = result.get("version", 0) + 1
    await prompts_col().update_one(
        {"agent": agent, "key": key},
        {"$set": {"template": body.template, "version": version, "updated_at": datetime.now(UTC)}},
    )
    return {"agent": agent, "key": key, "version": version}


@router.post("/{agent}/{key}/reset")
async def reset_prompt(agent: str, key: str):
    import pathlib

    import yaml

    prompts_dir = pathlib.Path(__file__).parent.parent.parent / "data" / "prompts"
    path = prompts_dir / f"{agent}.yaml"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"No seed file for agent '{agent}'")
    with open(path, "r") as f:
        data = yaml.safe_load(f)
    if key not in data:
        raise HTTPException(status_code=404, detail=f"Prompt key '{key}' not in seed file")
    await prompts_col().update_one(
        {"agent": agent, "key": key},
        {"$set": {"template": data[key], "version": 1, "updated_at": datetime.now(UTC)}},
        upsert=True,
    )
    return {"agent": agent, "key": key, "version": 1, "status": "reset"}
