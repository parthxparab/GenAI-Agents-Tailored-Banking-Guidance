import logging
from logging.config import dictConfig
from typing import Any, Dict

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import advisor, kyc, onboarding, support
from utils.redis_client import r

LOGGING_CONFIG: Dict[str, Any] = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default",
        },
    },
    "root": {"handlers": ["console"], "level": "INFO"},
}

dictConfig(LOGGING_CONFIG)
logger = logging.getLogger(__name__)

app = FastAPI(title="GenAI Banking API Gateway", version="1.0.0")
logger.info("Redis client initialised %s", r)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check() -> Dict[str, str]:
    """Simple health check endpoint used by the frontend."""
    return {"status": "ok"}


app.include_router(onboarding.router)
app.include_router(kyc.router)
app.include_router(advisor.router)
app.include_router(support.router)
