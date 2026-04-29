# SOP Driven Alert Analytics

An AIOps MVP for alert analytics with SOP-driven root cause analysis. Processes alerts through 3 AI agent stages (IdentifySOP, ExecuteSOP, ValidateRCA) using LangChain/LangGraph, with a NextJS feedback UI.

## Architecture

- **Backend**: Python FastAPI with RabbitMQ event processing
- **AI Agents**: LangGraph with GPT-4o mini, OpenAI text-embedding-3-small for RAG
- **Storage**: MongoDB (data), ChromaDB (vector embeddings)
- **Frontend**: NextJS static export served by FastAPI
- **Infrastructure**: docker-compose (app, RabbitMQ, MongoDB, ChromaDB)

## Prompt Management

LLM agent prompts are externalized and configurable at runtime without code changes. Two backends are supported, controlled by the `PROMPT_BACKEND` env var:

- **file** (default): Prompts stored as YAML in `data/prompts/`. Edit files and changes apply on the next alert processed, no restart needed.
- **db**: Prompts stored in MongoDB `prompts` collection. Editable at runtime via REST API. Falls back to file if a prompt is not found in the DB.

On startup, YAML prompts are seeded into MongoDB (idempotent). Set `PROMPT_BACKEND=db` in `.env` to switch to DB mode.

Prompt files: `data/prompts/identify_sop.yaml`, `data/prompts/execute_sop.yaml`, `data/prompts/validate_rca.yaml`

## Quick Start

1. Copy `.env.example` to `.env` and set `OPENAI_API_KEY`
2. Run `scripts/start.ps1` (Windows) or `sh scripts/start.sh` (Mac/Linux)
3. Seed sample data: `docker-compose exec app uv run python -m backend.identifySOP.seed` or `POST /api/sop-management/seed`
4. Open http://localhost:8000

## Local Development

```
cd backend && uv sync
cd frontend && npm install
```

- API: `uv run python -m backend.main web`
- Workers: `uv run python -m backend.main eventprocessing` (repeat for identifySOP, executeSOP, validateRCA)
- identifySOP  `uv run python -m backend.main identifySOP`
- executeSOP  `uv run python -m backend.main executeSOP`
- validateRCA  `uv run python -m backend.main validateRCA`
- Frontend dev: `cd frontend && npm run dev`

- mongodb data checking `uv run python scripts/check_db.py`
- chromadb data checking `uv run python scripts/check_rag_db.py`
- clean everything (SOPs + operational + ChromaDB) `uv run python scripts/clean_db.py --mode all --yes`
- clean operational data only (alerts, RCA, feedback) `uv run python scripts/clean_db.py --mode operational --yes`
- clean SOP data only (for re-seed) `uv run python scripts/clean_db.py --mode sop --yes`
- re-seed SOPs `uv run python -m backend.identifySOP.seed`
## Testing

- Unit tests: `uv run pytest backend/tests/`
- uv run python -m pytest backend/tests/test_models.py backend/tests/test_tools.py backend/tests/test_sop_management.py -v
- Pipeline test: `python scripts/test_pipeline.py`
- E2E tests: `cd frontend && npx playwright test`

## API Endpoints

- `POST /api/alerts` - Ingest alert
- `GET /api/alerts` - List alerts
- `GET /api/alerts/{id}` - Get alert
- `POST /api/webhooks/alerts` - Webhook ingestion
- `POST /api/sop/upload` - Upload SOP document (requires `sop_id` form field)
- `POST /api/sop/workflows` - Create SOP workflow
- `POST /api/sop-management/seed` - Seed all SOPs from mapping data
- `GET /api/sop-management/mappings` - List SOP mappings
- `GET /api/sop-management/mappings/{sop_id}` - Get mapping by sop_id
- `GET /api/sop-management/mapping-config` - View raw mapping config
- `GET /api/rca/{alert_id}` - Get RCA result
- `POST /api/feedback` - Submit feedback
- `GET /api/feedback/{alert_id}` - Get feedback
- `GET /api/prompts` - List all prompt templates
- `GET /api/prompts/{agent}/{key}` - Get a prompt template
- `PUT /api/prompts/{agent}/{key}` - Update a prompt template (body: `{"template": "..."}`) 
- `POST /api/prompts/{agent}/{key}/reset` - Reset prompt to YAML seed default
- `POST /api/retries` - Submit a retry batch
- `GET /api/retries/{batch_id}` - Get retry batch status and stage events
- `GET /api/retries/{batch_id}/run-output?alert_id={id}` - Get RCA, validation, and classifier match for a retry run
- `GET /api/alerts/{id}/retries` - Get all retry history for an alert

## Retry

Retry allows re-processing one or more alerts from a chosen pipeline stage without losing the original data. All prior outputs are soft-invalidated (marked inactive) rather than deleted, preserving audit history.

### Retry Levels

| Level | Enters queue at | Reruns stages |
|-------|----------------|---------------|
| `level1` | `alert_ingest` | All 3 stages (IdentifySOP → ExecuteSOP → ValidateRCA) |
| `level2` | `stage1_identify` | Stage 1 onwards (IdentifySOP → ExecuteSOP → ValidateRCA) |
| `level3` | `stage2_execute` | Stage 2 onwards (ExecuteSOP → ValidateRCA). Requires SOP already identified. |
| `level4` | `stage3_validate` | Stage 3 only (ValidateRCA). Requires RCA already present. |

### How to Submit a Retry

**Via UI:** Open the Retry tab, select one or more alerts from the left panel, choose a retry level, and click Submit.

**Via API:**
```bash
POST /api/retries
{
  "alert_ids": ["<alert_id>"],
  "retry_level": "level1",
  "reason": "optional note"
}
```
Returns a `batch_id` that identifies the retry run.

### Retry State Transitions

```
queued → running_stage1 → running_stage2 → running_stage3 → completed
                                                           → failed
```

### Checking Retry Status

**UI:** The Retry tab shows live state per alert (queued / running_stage1 / ... / completed / failed). Click "View Details" on a completed retry to see the SOP match, RCA, and confidence score.

**API:**
```bash
# Batch-level status + per-alert states + stage events
GET /api/retries/{batch_id}

# Full RCA + validation output for one alert in a batch
GET /api/retries/{batch_id}/run-output?alert_id={alert_id}

# All retry history for an alert
GET /api/alerts/{alert_id}/retries
```

**MongoDB:** Retry data is stored in these collections:
- `alert_retry_attempts` - one document per alert per batch, tracks current state
- `retry_stage_events` - stage-level start/complete/fail events for a batch
- `rca_results` - RCA documents tagged with `retry_batch_id` and `is_active_latest`
- `validation_results` - validation documents tagged with `retry_batch_id`
- `classifier_match_logs` - SOP match logs tagged with `retry_batch_id`

**Scripts:**
```powershell
# Check retry data in MongoDB
uv run python scripts/check_retry_db.py

# Check which workers are running (local vs Docker)
.\scripts\check_workers.ps1
```
