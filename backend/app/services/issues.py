import re
import traceback
from typing import Any, Dict, List, Optional

import httpx

from ..github import create_issue, ensure_labels, find_issue_by_fp, task_fingerprint
from ..storage import load_chunks
from ..storage import record_publication
from .errors import ServiceError
from .shared import append_source_snippet, build_snippet_map, coerce_labels, validate_meeting_id


class IssueService:
    repo_pattern = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")

    def __init__(self, public_demo_mode: bool = False) -> None:
        self.public_demo_mode = public_demo_mode

    def validate_repo(self, repo: str) -> None:
        if self.repo_pattern.match(repo):
            return
        raise ServiceError(
            status_code=400,
            where="client",
            error=f'Invalid repo "{repo}". Use "owner/repo".',
        )

    def preview_issues(self, repo: str, meeting_id: Optional[str], tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
        self.validate_repo(repo)
        snippet_by_i: Dict[int, str] = {}
        if meeting_id:
            validate_meeting_id(meeting_id)
            snippet_by_i = build_snippet_map(load_chunks(meeting_id))

        preview = []
        for task in tasks:
            body = str(task.get("body", "") or "")
            body = append_source_snippet(body, meeting_id, task.get("source_i"), snippet_by_i)
            preview.append(
                {
                    "repo": repo,
                    "title": task.get("title", "(no title)"),
                    "body": body,
                    "labels": coerce_labels(task.get("labels")),
                }
            )
        return {"would_create": preview}

    async def create_issues(
        self,
        repo: str,
        meeting_id: Optional[str],
        tasks: List[Dict[str, Any]],
        assignee_map: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        if self.public_demo_mode:
            raise ServiceError(
                status_code=403,
                where="client",
                error="Public demo mode is preview-only. GitHub issue creation is disabled.",
            )
        self.validate_repo(repo)
        assignee_map = assignee_map or {}

        try:
            snippet_by_i: Dict[int, str] = {}
            if meeting_id:
                validate_meeting_id(meeting_id)
                snippet_by_i = build_snippet_map(load_chunks(meeting_id))

            all_labels = sorted({label for task in tasks for label in coerce_labels(task.get("labels"))})
            if all_labels:
                await ensure_labels(repo, all_labels)

            created = []
            for task in tasks:
                title = str(task.get("title") or "").strip()
                if not title:
                    created.append({"title": "(empty)", "status": "skipped-empty-title"})
                    continue

                body = str(task.get("body") or "").strip()
                fingerprint = task_fingerprint(title, body)
                body += f"\n\n<!-- mtg:{meeting_id} fp:{fingerprint} -->"
                body = append_source_snippet(body, meeting_id, task.get("source_i"), snippet_by_i)

                existing = await find_issue_by_fp(repo, fingerprint)
                if existing:
                    record_publication(
                        meeting_id,
                        repo,
                        title,
                        fingerprint,
                        "skipped-duplicate",
                        existing["number"],
                        existing["html_url"],
                    )
                    created.append(
                        {
                            "number": existing["number"],
                            "url": existing["html_url"],
                            "title": title,
                            "status": "skipped-duplicate",
                        }
                    )
                    continue

                gh_user = None
                hint = task.get("assignee_hint")
                if isinstance(hint, str):
                    gh_user = assignee_map.get(hint) or assignee_map.get(hint.lower())

                issue = await create_issue(
                    repo,
                    title,
                    body,
                    labels=coerce_labels(task.get("labels")),
                    assignee=gh_user,
                )
                record_publication(
                    meeting_id,
                    repo,
                    title,
                    fingerprint,
                    "created",
                    issue["number"],
                    issue["html_url"],
                )
                created.append(
                    {
                        "number": issue["number"],
                        "url": issue["html_url"],
                        "title": title,
                        "status": "created",
                    }
                )

            return {"created": created}
        except httpx.HTTPStatusError as exc:
            raise ServiceError(
                status_code=502,
                where="github",
                error=exc.response.text,
                extra={"status": exc.response.status_code, "text": exc.response.text},
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise ServiceError(
                status_code=500,
                where="server",
                error=str(exc),
                extra={"trace_tail": traceback.format_exc().splitlines()[-4:]},
            ) from exc
