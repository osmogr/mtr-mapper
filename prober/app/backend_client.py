import logging

import httpx

from app.config import Settings
from app.mtr_runner import TraceResult

logger = logging.getLogger(__name__)


class BackendClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.backend_url,
            headers={"Authorization": f"Bearer {settings.prober_api_token}"},
            timeout=15.0,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def get_targets(self) -> list[dict]:
        resp = await self._client.get("/api/prober/targets")
        resp.raise_for_status()
        return resp.json()

    async def submit_result(self, result: TraceResult) -> None:
        payload = {
            "target_id": result.target_id,
            "started_at": result.started_at.isoformat(),
            "completed_at": result.completed_at.isoformat(),
            "success": result.success,
            "error_message": result.error_message,
            "raw_json": result.raw_json,
            "hops": [
                {
                    "hop_number": h.hop_number,
                    "hop_ip": h.hop_ip,
                    "hop_hostname": h.hop_hostname,
                    "is_timeout": h.is_timeout,
                    "sent": h.sent,
                    "loss_pct": h.loss_pct,
                    "last_ms": h.last_ms,
                    "avg_ms": h.avg_ms,
                    "best_ms": h.best_ms,
                    "worst_ms": h.worst_ms,
                    "stddev_ms": h.stddev_ms,
                }
                for h in result.hops
            ],
        }
        resp = await self._client.post("/api/prober/results", json=payload)
        if resp.status_code == 404:
            # Target was deleted/deactivated between being handed to us and finishing the probe.
            logger.info("target %s no longer active, dropping result", result.target_id)
            return
        resp.raise_for_status()
