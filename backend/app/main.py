import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import admin_target_lists, admin_targets, auth, prober, tree, ws
from app.config import get_settings
from app.db import async_session_maker
from app.services.retention import retention_loop
from app.services.target_list_sync import sync_loop
from app.services.tree_service import tree_service
from app.services.ws_manager import manager as ws_manager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    tasks = [
        asyncio.create_task(
            tree_service.debounce_loop(
                async_session_maker, settings, ws_manager, settings.tree_recompute_interval_seconds
            )
        ),
        asyncio.create_task(sync_loop(async_session_maker)),
        asyncio.create_task(
            retention_loop(
                async_session_maker,
                settings.trace_retention_hours,
                settings.retention_sweep_interval_seconds,
            )
        ),
    ]
    logger.info("mtr-mapper backend started, background tasks running")
    yield
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(title="mtr-mapper", lifespan=lifespan)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(admin_targets.router)
app.include_router(admin_target_lists.router)
app.include_router(tree.router)
app.include_router(prober.router)
app.include_router(ws.router)
