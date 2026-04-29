"""Bird species classification using Claude API."""

import base64
import logging
import os

import anthropic

from birdcam.config import ClassifierConfig
from birdcam.db import DetectionDB

log = logging.getLogger(__name__)

PROMPT = """Identify the bird species in this photo. Respond with ONLY the common name
of the bird (e.g. "Black-capped Chickadee"). If you cannot identify the species with
reasonable confidence, respond with "Unknown". If there is no bird in the image,
respond with "Not a bird"."""


class Classifier:
    def __init__(self, config: ClassifierConfig, db: DetectionDB):
        self._config = config
        self._db = db
        self._client: anthropic.Anthropic | None = None

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            log.warning(
                "ANTHROPIC_API_KEY not set — species classification disabled"
            )
            self._enabled = False
        else:
            self._client = anthropic.Anthropic(api_key=api_key)
            self._enabled = config.enabled
            log.info(
                "Classifier ready (model=%s, limit=%d/day)",
                config.model,
                config.max_requests_per_day,
            )

    @property
    def enabled(self) -> bool:
        return self._enabled

    def classify(self, detection_id: int, jpeg_data: bytes) -> str | None:
        """Classify a bird detection. Returns species name or None if skipped."""
        if not self._enabled or self._client is None:
            return None

        today_count = self._db.classifications_today()
        if today_count >= self._config.max_requests_per_day:
            log.warning(
                "Daily classification limit reached (%d/%d)",
                today_count,
                self._config.max_requests_per_day,
            )
            return None

        try:
            image_b64 = base64.standard_b64encode(jpeg_data).decode("utf-8")

            message = self._client.messages.create(
                model=self._config.model,
                max_tokens=100,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/jpeg",
                                    "data": image_b64,
                                },
                            },
                            {
                                "type": "text",
                                "text": PROMPT,
                            },
                        ],
                    }
                ],
            )

            species = message.content[0].text.strip()
            self._db.set_species(detection_id, species)
            log.info("Detection #%d classified as: %s", detection_id, species)
            return species

        except Exception:
            log.exception("Classification failed for detection #%d", detection_id)
            return None
