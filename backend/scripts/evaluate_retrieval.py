from __future__ import annotations

import json
import tempfile
from pathlib import Path

from app import storage
from app.embeddings import embed_texts_hash
from app.main import DEMO_TRANSCRIPT
from app.services.meetings import MeetingService
from app.vectorstore.memory_store import MemoryStore


def main() -> None:
    cases_path = Path(__file__).parents[1] / "evals" / "retrieval_cases.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))

    with tempfile.TemporaryDirectory(prefix="meeting-to-tasks-eval-") as directory:
        storage.DATA_ROOT = Path(directory)
        service = MeetingService(MemoryStore(), "hash-v1", embed_texts_hash)
        service.index_meeting_text("eval-demo", "Retrieval evaluation", DEMO_TRANSCRIPT)

        hits = 0
        latencies = []
        rows = []
        for case in cases:
            result = service.search("eval-demo", case["query"], k=1)
            actual = result["results"][0]["source"]["chunk_i"]
            matched = actual == case["expected_chunk"]
            hits += int(matched)
            latencies.append(result["timings"]["retrieval_ms"])
            rows.append({"query": case["query"], "expected": case["expected_chunk"], "actual": actual, "hit": matched})

    report = {
        "strategy": "hybrid-vector-lexical",
        "cases": len(cases),
        "recall_at_1": round(hits / len(cases), 3),
        "average_retrieval_ms": round(sum(latencies) / len(latencies), 2),
        "results": rows,
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
