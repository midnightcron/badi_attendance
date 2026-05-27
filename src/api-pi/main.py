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
from contextlib import asynccontextmanager

from db import create_pool
from routes import health, occupancy, dashboard

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S%z",
    stream=sys.stdout,
)
structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(LOG_LEVEL)),
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = await create_pool()
    yield
    await app.state.pool.close()


app = FastAPI(title="Badi Occupancy API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
)

app.include_router(health.router, prefix="/api")
app.include_router(occupancy.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
