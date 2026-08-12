from typing import Any, Dict, Optional


class ServiceError(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        error: str,
        where: str = "server",
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(error)
        detail: Dict[str, Any] = {"where": where, "error": error}
        if extra:
            detail.update(extra)

        self.status_code = status_code
        self.detail = detail
