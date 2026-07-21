import asyncio
import logging

from app.backend_client import BackendClient
from app.config import get_settings
from app.scheduler import Scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


async def main() -> None:
    settings = get_settings()
    logger.info(
        "prober starting: concurrency=%d min_cycle=%ds backend=%s",
        settings.prober_concurrency,
        settings.prober_min_cycle_seconds,
        settings.backend_url,
    )
    backend = BackendClient(settings)
    scheduler = Scheduler(settings, backend)
    try:
        await scheduler.run()
    finally:
        await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
