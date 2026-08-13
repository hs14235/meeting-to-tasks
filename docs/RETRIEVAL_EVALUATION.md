# Retrieval Evaluation

The repository includes a deterministic offline benchmark at
`backend/evals/retrieval_cases.json`. It tests whether four representative queries retrieve the
expected timestamped source turn from the demo transcript.

Run it from `backend`:

```powershell
.\.venv\Scripts\python -m scripts.evaluate_retrieval
```

Current measured baseline on 2026-08-13:

| Strategy | Cases | Recall@1 | Average retrieval |
| --- | ---: | ---: | ---: |
| Hybrid hash-vector + lexical | 4 | 1.00 | 1.82 ms |

The hash embedder makes the benchmark fast, reproducible, and offline. This is an engineering
baseline rather than a claim about semantic production quality. The next meaningful experiment is
to expand the labeled set, compare vector-only against hybrid retrieval, and report confidence
intervals plus source-mapping accuracy.
