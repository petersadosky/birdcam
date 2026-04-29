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
        self._error: str | None = None

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            log.warning(
                "ANTHROPIC_API_KEY not set — species classification disabled"
            )
            self._enabled = False
            self._error = "API key not configured"
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

    @property
    def status(self) -> dict:
        """Return classifier status for the web UI."""
        if not self._enabled and self._error:
            return {"ok": False, "message": self._error}
        today = self._db.classifications_today()
        limit = self._config.max_requests_per_day
        if today >= limit:
            return {"ok": False, "message": f"Daily limit reached ({today}/{limit})"}
        return {"ok": True, "message": None}

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

            # Clear any previous error on success
            self._error = None

            log.info("Detection #%d classified as: %s", detection_id, species)
            return species

        except anthropic.AuthenticationError:
            self._error = "Invalid API key"
            self._enabled = False
            log.error("Invalid API key — classifier disabled")
            return None

        except anthropic.PermissionDeniedError:
            self._error = "API access denied — check your Anthropic account"
            self._enabled = False
            log.error("Permission denied — classifier disabled")
            return None

        except anthropic.RateLimitError:
            self._error = "Rate limited — will retry on next detection"
            log.warning("Rate limited by Anthropic API")
            return None

        except anthropic.APIStatusError as e:
            if e.status_code == 402 or "billing" in str(e).lower() or "funds" in str(e).lower():
                self._error = "Anthropic account out of funds — add credits at console.anthropic.com"
                self._enabled = False
                log.error("Out of funds — classifier disabled")
            else:
                self._error = f"API error (HTTP {e.status_code})"
                log.error("API error: %s", e)
            return None

        except anthropic.APIConnectionError:
            self._error = "Cannot reach Anthropic API — check internet connection"
            log.warning("Connection error to Anthropic API")
            return None

        except Exception:
            log.exception("Classification failed for detection #%d", detection_id)
            return None
