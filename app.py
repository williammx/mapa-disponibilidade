"""Hugging Face Spaces launcher for the FastAPI backend."""

import os

import gradio as gr
import spaces
import uvicorn

from api import app as api_app


@spaces.GPU
def health_probe():
    """Satisfy ZeroGPU startup detection without moving PDF work to the GPU."""
    return "ok"


demo = gr.Blocks()
app = gr.mount_gradio_app(api_app, demo, path="/")


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", "7860")),
        log_level="info",
    )
