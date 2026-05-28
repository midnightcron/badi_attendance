"""
FastAPI application for badi occupancy data.

Replaces the Azure Function App (src/api/).

Routes:
    GET /api/health_check
    GET /api/occupancy
    GET /api/dashboard
"""

import logging
import os
import sys

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager

from db import create_pool
from routes import health, occupancy, dashboard, v2

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S%z",
    stream=sys.stdout,
)
_level_int = logging.getLevelName(LOG_LEVEL)
structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(_level_int),
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = await create_pool()
    app.state.templates = Jinja2Templates(directory="templates")
    yield
    await app.state.pool.close()


app = FastAPI(title="Badi Occupancy API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
)

# v2 owns the root path and the /pool/{location} pages
app.include_router(v2.router)

# legacy + JSON API live under /api
app.include_router(health.router, prefix="/api")
app.include_router(occupancy.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
