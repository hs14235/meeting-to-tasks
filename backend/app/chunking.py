from __future__ import annotations

import re
from typing import Any

CHUNKING_VERSION = "paragraph-overlap-v2"
SPEAKER_PATTERN = re.compile(r"^(?:\[(?P<timestamp>\d{1,2}:\d{2}(?::\d{2})?)\]\s*)?(?P<speaker>[A-Z][\w .'-]{1,40}):\s+")


def to_chunk_records(text: str, approx_tokens: int = 180, overlap_lines: int = 1) -> list[dict[str, Any]]:
    lines = [(index + 1, line.strip()) for index, line in enumerate(text.splitlines()) if line.strip()]
    if not lines:
        return []

    # Timestamped speaker turns are already natural evidence boundaries. Keeping
    # them separate gives task citations a precise, human-readable source.
    if all(SPEAKER_PATTERN.match(line) for _, line in lines):
        records = []
        for index, (line_number, line) in enumerate(lines):
            match = SPEAKER_PATTERN.match(line)
            records.append(
                {
                    "i": index,
                    "text": line,
                    "speaker": match.group("speaker"),
                    "timestamp": match.group("timestamp"),
                    "start_line": line_number,
                }
            )
        return records

    records: list[dict[str, Any]] = []
    start = 0
    while start < len(lines):
        end = start
        words = 0
        while end < len(lines) and (words < approx_tokens or end == start):
            words += len(lines[end][1].split())
            end += 1

        selected = lines[start:end]
        first_match = SPEAKER_PATTERN.match(selected[0][1])
        records.append(
            {
                "i": len(records),
                "text": "\n".join(line for _, line in selected),
                "speaker": first_match.group("speaker") if first_match else None,
                "timestamp": first_match.group("timestamp") if first_match else None,
                "start_line": selected[0][0],
            }
        )
        if end >= len(lines):
            break
        start = max(start + 1, end - overlap_lines)
    return records


def to_chunks(text: str, approx_tokens: int = 180) -> list[str]:
    return [record["text"] for record in to_chunk_records(text, approx_tokens=approx_tokens)]
