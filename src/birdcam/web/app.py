"""FastAPI web application for browsing bird detections."""

import asyncio
import logging
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from birdcam.buffer import FrameBuffer
from birdcam.classifier import Classifier
from birdcam.db import DetectionDB
from birdcam.storage import Storage

log = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"


def create_app(db: DetectionDB, storage: Storage, frame_buffer: FrameBuffer | None = None, classifier: Classifier | None = None) -> FastAPI:
    app = FastAPI(title="BirdCam")
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    # Template filters
    def format_timestamp(ts: float) -> str:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")

    def format_confidence(conf: float) -> str:
        return f"{conf:.0%}"

    templates.env.filters["timestamp"] = format_timestamp
    templates.env.filters["confidence"] = format_confidence

    @app.get("/", response_class=HTMLResponse)
    async def index(
        request: Request,
        page: int = Query(1, ge=1),
    ):
        per_page = 24
        offset = (page - 1) * per_page
        detections = db.list_detections(limit=per_page, offset=offset)
        total = db.count()
        total_pages = max(1, (total + per_page - 1) // per_page)

        classifier_status = classifier.status if classifier else {"ok": True, "message": None}

        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "detections": detections,
                "page": page,
                "total_pages": total_pages,
                "total": total,
                "classifier_status": classifier_status,
            },
        )

    @app.get("/detection/{detection_id}", response_class=HTMLResponse)
    async def detail(request: Request, detection_id: int):
        detection = db.get(detection_id)
        if detection is None:
            return HTMLResponse("Not found", status_code=404)
        return templates.TemplateResponse(
            request=request,
            name="detail.html",
            context={"d": detection},
        )

    @app.post("/detection/{detection_id}/delete")
    async def delete_detection(detection_id: int):
        detection = db.get(detection_id)
        if detection is None:
            return HTMLResponse("Not found", status_code=404)
        storage.delete_detection(detection_id)
        return RedirectResponse(url="/", status_code=303)

    @app.get("/images/{path:path}")
    async def serve_image(path: str):
        """Serve images from the storage directory."""
        try:
            full_path = storage.resolve_path(path)
        except ValueError:
            return HTMLResponse("Forbidden", status_code=403)
        if not full_path.exists():
            return HTMLResponse("Not found", status_code=404)
        return FileResponse(full_path, media_type="image/jpeg")

    @app.get("/live", response_class=HTMLResponse)
    async def live(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="live.html",
            context={},
        )

    @app.get("/stream")
    async def stream():
        """MJPEG stream of live camera frames."""
        if frame_buffer is None:
            return HTMLResponse("No camera available", status_code=503)

        async def generate():
            while True:
                frame = frame_buffer.latest()
                if frame is not None:
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n"
                        + frame.jpeg_data
                        + b"\r\n"
                    )
                await asyncio.sleep(0.2)  # ~5 FPS

        return StreamingResponse(
            generate(),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )

    return app
