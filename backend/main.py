import asyncio
import logging
import sys
import threading

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.routes import alerts, feedback, prompts, rca, retry, sop, tools as tools_routes, webhooks
from backend.sopmanagement import routes as sop_management_routes

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def _startup_seed():
    """Background task: seed SOPs and repair any MongoDB/ChromaDB drift on startup."""
    await asyncio.sleep(8)  # Allow MongoDB and ChromaDB containers to become ready
    try:
        from backend.sopmanagement.service import seed_all
        results = await asyncio.to_thread(seed_all)
        seeded = sum(1 for r in results if r.get("status") == "seeded")
        resynced = sum(1 for r in results if r.get("status") == "resynced_chroma")
        skipped = sum(1 for r in results if r.get("status") == "skipped")
        errors = sum(1 for r in results if r.get("status") == "error")
        logger.info("Startup seed: seeded=%d resynced_chroma=%d skipped=%d errors=%d", seeded, resynced, skipped, errors)
    except Exception as e:
        logger.error("Startup seed failed: %s", e)
    try:
        from backend.prompts.seed import seed_prompts
        count = await asyncio.to_thread(seed_prompts)
        logger.info("Prompt seed: %d new prompts seeded", count)
    except Exception as e:
        logger.error("Prompt seed failed: %s", e)
    try:
        from backend.tools.seeder import seed_tools
        count = await asyncio.to_thread(seed_tools)
        logger.info("Tool seed: %d new tools seeded", count)
    except Exception as e:
        logger.error("Tool seed failed: %s", e)


from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(_startup_seed())
    yield


app = FastAPI(title="SOP Driven Alert Analytics", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

app.include_router(alerts.router)
app.include_router(sop.router)
app.include_router(sop_management_routes.router)
app.include_router(rca.router)
app.include_router(feedback.router)
app.include_router(webhooks.router)
app.include_router(prompts.router)
app.include_router(retry.router)
app.include_router(tools_routes.router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


# Serve frontend static files if available
import pathlib

_frontend = pathlib.Path(__file__).parent.parent / "frontend" / "out"
if _frontend.exists():
    app.mount("/", StaticFiles(directory=str(_frontend), html=True), name="frontend")


def _run_web():
    uvicorn.run(app, host="0.0.0.0", port=8000)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "web"

    if mode == "web":
        _run_web()
    elif mode == "eventprocessing":
        from backend.eventprocessing.worker import run
        run()
    elif mode == "identifySOP":
        from backend.identifySOP.agent import run_worker
        run_worker()
    elif mode == "executeSOP":
        from backend.executeSOP.agent import run_worker
        run_worker()
    elif mode == "validateRCA":
        from backend.validateRCA.agent import run_worker
        run_worker()
    else:
        print(f"Unknown mode: {mode}")
        sys.exit(1)


if __name__ == "__main__":
    main()
