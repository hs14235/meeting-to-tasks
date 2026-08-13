# Meeting to Tasks

Meeting to Tasks turns plain-text meeting transcripts into reviewable task drafts and optional GitHub issues.

## What it does

- Upload and index UTF-8 meeting transcripts.
- Retrieve the most relevant chunks for prompts such as action items or risks.
- Extract task candidates with Ollama when available.
- Fall back to a narrow rule-based extractor for explicit action lines.
- Preview GitHub issues before creating anything.
- Review and edit source-grounded drafts in a responsive meeting workspace.
- Persist meetings, chunks, drafts, and publication history in SQLite.
- Use the same application services from REST and an MCP client.

## Supported uploads

Today the app honestly supports:

- `.txt`
- `.md`

Both must be UTF-8 encoded. PDF, Word, and rich-text parsing are intentionally not implemented yet.

## Stack

- FastAPI backend
- React + Vite frontend
- SQLite durable application state
- Sentence Transformers embeddings
- FAISS with memory fallback
- Ollama for local task extraction
- GitHub REST API for issue creation
- MCP Python SDK 2.0 for LLM tool integration

## Architecture

The React interface and MCP server are two adapters over the same application services:

```text
React UI -> FastAPI routes ----\
                              -> meeting, extraction, and GitHub services
LLM client -> MCP tools ------/
```

The web UI remains the human-facing product. MCP adds a structured interface for Codex and other
compatible LLM clients without duplicating retrieval, extraction, or issue-creation logic.

## Quick start

### 1. Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Set these values in `backend/.env` if you need them:

```env
GITHUB_TOKEN=
OLLAMA_URL=http://127.0.0.1:11434
OLLAMA_MODEL=phi3:mini
RAG_STORE=memory
EMBED_MODEL=sentence-transformers/all-MiniLM-L6-v2
EMBED_PROVIDER=sentence-transformers
PUBLIC_DEMO_MODE=false
RETRIEVAL_THRESHOLD=0.08
```

Run the API:

```powershell
.\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

### 2. Frontend

```powershell
cd ../frontend
npm install
Copy-Item .env.example .env
npm run dev
```

The frontend expects `VITE_API_BASE=http://127.0.0.1:8000` by default.

### 3. MCP server

Run the local stdio server from `backend`:

```powershell
.\.venv\Scripts\python -m app.mcp_server
```

The server exposes five structured tools:

- `index_meeting`
- `search_meeting`
- `extract_meeting_tasks`
- `preview_github_issues`
- `create_github_issues`

`create_github_issues` is annotated as an external, destructive write. Clients should require
explicit approval before calling it. The other GitHub tool only previews payloads.

For local HTTP development, run a stateless Streamable HTTP server on port 8001:

```powershell
.\.venv\Scripts\python -m app.mcp_server --transport streamable-http --port 8001
```

Its MCP endpoint is `http://127.0.0.1:8001/mcp`. This local endpoint has no authentication and
must not be exposed publicly. A deployable remote MCP server needs HTTPS, authentication, and a
public host; that is intentionally deferred to the deployment phase.

### 4. MCP workflow demo

Run the complete safe workflow through an independent MCP client:

```powershell
cd backend
.\.venv\Scripts\python -m scripts.demo_mcp_workflow
```

The demo starts the stdio server, discovers its tools, indexes a temporary transcript, searches
the indexed context, extracts sourced tasks, and previews GitHub issues. It intentionally never
calls `create_github_issues`.

The demo sets `EMBED_PROVIDER=hash` in its isolated server process. This deterministic lexical
provider keeps tests offline and fast; normal application usage defaults to Sentence Transformers.

This repository also includes a project-scoped Codex configuration in `.codex/config.toml`.
After trusting and reopening the project, the ChatGPT desktop app, Codex CLI, or IDE extension can
start the server over stdio. Write-capable tools require approval, and `create_github_issues` always
prompts. The included command targets the Windows virtual-environment layout used by this project.

### 5. Optional local LLM

If you want broader extraction than the rules fallback:

```powershell
winget install Ollama.Ollama
ollama pull phi3:mini
```

If Ollama is not running, the app still works, but only the rule-based extractor will fire.

If you want FAISS instead of the default in-memory store, install it separately and set `RAG_STORE=faiss`.

## Validation

Run backend tests:

```powershell
cd backend
python -m pytest
```

Expected result: `16 passed`.

Run frontend checks:

```powershell
cd frontend
npm run typecheck
npm run build
```

Run the deterministic retrieval evaluation:

```powershell
cd backend
.\.venv\Scripts\python -m scripts.evaluate_retrieval
```

The current four-case baseline reports `1.00 recall@1`. See
[`docs/RETRIEVAL_EVALUATION.md`](docs/RETRIEVAL_EVALUATION.md) for scope and limitations.

For the data model, trust boundaries, hybrid scoring, and SQLite/PostgreSQL rationale, see
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Project notes

- `data/sample.txt` and `data/sample2.txt` are sample transcripts.
- Generated FAISS indexes, meeting artifacts, virtual environments, and caches should stay out of git.
- The streaming extractor now normalizes source chunk indices before previewing or creating issues.
