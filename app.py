"""Hugging Face Spaces launcher for the FastAPI backend."""

import os

import uvicorn

from api import app


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", "7860")),
        log_level="info",
    )
