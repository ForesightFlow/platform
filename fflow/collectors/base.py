import asyncio
import random
from abc import ABC, abstractmethod
from datetime import UTC, datetime

import httpx
from pydantic import BaseModel

from fflow.config import settings
from fflow.log import get_logger

log = get_logger(__name__)

_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


class CollectorResult(BaseModel):
    collector: str
    target: str | None = None
    n_written: int = 0
    started_at: datetime
    finished_at: datetime | None = None
    status: str = "running"
    error: str | None = None


class RetryableHTTPClient:
    def __init__(self, base_url: str = "", headers: dict | None = None) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers=headers or {},
            timeout=settings.http_timeout_seconds,
            http2=True,
        )

    async def get(self, url: str, **kwargs) -> httpx.Response:
        return await self._request("GET", url, **kwargs)

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(settings.http_max_retries + 1):
            try:
                resp = await self._client.request(method, url, **kwargs)
                if resp.status_code not in _RETRYABLE_STATUS:
                    return resp
                retry_after = resp.headers.get("Retry-After")
                wait = float(retry_after) if retry_after else self._backoff(attempt)
                log.warning(
                    "http_retry",
                    url=url,
                    status=resp.status_code,
                    attempt=attempt + 1,
                    wait_s=wait,
                )
            except (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError) as exc:
                last_exc = exc
                wait = self._backoff(attempt)
                log.warning(
                    "http_retry",
                    url=url,
                    error=str(exc),
                    attempt=attempt + 1,
                    wait_s=wait,
                )
            if attempt < settings.http_max_retries:
                await asyncio.sleep(wait)

        if last_exc:
            raise last_exc
        raise httpx.HTTPStatusError(
            f"Max retries exceeded for {url}", request=httpx.Request(method, url), response=resp
        )

    def _backoff(self, attempt: int) -> float:
        base = settings.http_backoff_base_seconds
        jitter = random.uniform(0, base)
        return min(base * (2**attempt) + jitter, 60.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "RetryableHTTPClient":
        return self

    async def __aexit__(self, *_) -> None:
        await self.aclose()


class BaseCollector(ABC):
    name: str

    @abstractmethod
    async def run(self, target: str | None = None, **kwargs) -> CollectorResult:
        ...

    def _start_result(self, target: str | None = None) -> CollectorResult:
        return CollectorResult(
            collector=self.name,
            target=target,
            started_at=datetime.now(UTC),
        )

    async def _record_run_start(self, session, result: CollectorResult) -> int:
        from sqlalchemy import text

        row = await session.execute(
            text(
                "INSERT INTO data_collection_runs "
                "(collector, started_at, status, target) "
                "VALUES (:c, :s, 'running', :t) RETURNING id"
            ),
            {"c": result.collector, "s": result.started_at, "t": result.target},
        )
        await session.commit()
        return row.scalar_one()

    async def _record_run_end(
        self, session, run_id: int, result: CollectorResult
    ) -> None:
        from sqlalchemy import text

        await session.execute(
            text(
                "UPDATE data_collection_runs SET "
                "finished_at=:f, status=:s, n_records_written=:n, error_message=:e "
                "WHERE id=:id"
            ),
            {
                "f": result.finished_at,
                "s": result.status,
                "n": result.n_written,
                "e": result.error,
                "id": run_id,
            },
        )
        await session.commit()
