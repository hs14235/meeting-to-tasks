# Architecture and Trust Boundaries

## Product boundary

Meeting to Tasks has two adapters over the same application layer:

```text
React workspace -> FastAPI ----\
                                -> meeting, extraction, and issue services
LLM client -----> MCP server --/
```

The React workspace is the human review surface. MCP makes the same capabilities available to
compatible LLM clients without creating a second implementation of indexing, retrieval, task
extraction, or GitHub publication.

## Data responsibilities

- SQLite is the durable system of record for meetings, transcript chunks, editable task drafts,
  and publication history.
- FAISS is an optional derived similarity index. It can be rebuilt and never owns business state.
- The content hash, embedding model, and chunking version make indexing idempotent and expose when
  vectors must be replaced.
- Timestamped speaker turns remain discrete chunks. Generic prose uses bounded chunks with overlap.
- Re-index and delete operations remove stale vectors as well as relational records.

SQLite is deliberate for a local-first portfolio product: it provides transactions, foreign keys,
simple test isolation, and zero service setup. PostgreSQL is the intended migration when concurrent
users, hosted workers, or row-level authorization become requirements. MongoDB would add operational
complexity without improving this strongly relational workflow.

## Retrieval

Search ranks every stored source chunk using a weighted score:

```text
hybrid score = 0.72 * normalized vector similarity + 0.28 * lexical overlap
```

Results below the configured threshold are removed. One best-effort fallback result is returned when
none qualify so extraction can report a narrow fallback rather than silently failing. Every result
contains evidence text, meeting ID, chunk index, speaker, timestamp, source line, component scores,
strategy metadata, and timing.

## External-write safety

- Issue payloads are previewed before publication.
- The web UI requires an explicit browser confirmation before a GitHub write.
- The MCP write tool is marked destructive and open-world for client approval policies.
- Duplicate fingerprints prevent repeated issue creation.
- `PUBLIC_DEMO_MODE=true` disables GitHub writes at the service layer, not only in the UI.
- A public deployment must never expose a personal GitHub token to visitors.

## Known boundaries

- Upload support is intentionally limited to UTF-8 `.txt` and `.md` files.
- Rule extraction recognizes explicit action language; Ollama broadens extraction when configured.
- The included evaluation set is small and proves the harness, not production-scale retrieval quality.
- A remote MCP endpoint still requires HTTPS, authentication, per-user authorization, and rate limits.
