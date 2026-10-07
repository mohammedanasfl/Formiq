"""Gemini, called through the Google GenAI SDK (google-genai).

The provider only turns a message into a reply. It reads no Formiq data.
"""

import logging
import math

from google import genai
from google.genai import types

from app.ai.exceptions import AIProviderError, AIProviderNotConfiguredError

logger = logging.getLogger(__name__)


class GeminiProvider:
    def __init__(self, api_key: str | None, model: str, *, timeout_seconds: float) -> None:
        self.model = model
        # The key is always passed explicitly, so the SDK never falls back to
        # other environment variables. Without a key there is no client.
        self._client = (
            genai.Client(
                api_key=api_key,
                # The SDK takes milliseconds, and reads 0 as no timeout, so it is
                # rounded up. Without retry_options it makes a single attempt.
                http_options=types.HttpOptions(timeout=math.ceil(timeout_seconds * 1000)),
            )
            if api_key
            else None
        )

    def generate(self, message: str, *, instructions: str) -> str:
        """The model's reply to the message, following the system instructions."""
        if self._client is None:
            raise AIProviderNotConfiguredError("GEMINI_API_KEY is not set")
        try:
            response = self._client.models.generate_content(
                model=self.model,
                contents=message,
                config=types.GenerateContentConfig(system_instruction=instructions),
            )
        except Exception as error:
            # The cause, such as a rate limit, a network error or a timeout, goes
            # to the server log only.
            logger.exception("Gemini request to %s failed", self.model)
            raise AIProviderError(f"the {self.model} request failed") from error
        if not response.text:
            # for example when the prompt or the reply was blocked
            logger.warning("%s returned no text: %s", self.model, response.prompt_feedback)
            raise AIProviderError(f"{self.model} returned no text")
        return response.text
