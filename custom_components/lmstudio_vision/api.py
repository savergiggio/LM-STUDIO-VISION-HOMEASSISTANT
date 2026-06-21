"""Thin async client for the LM Studio server.

Covers the OpenAI-compatible endpoints (/v1/*) used for inference plus the
native endpoints needed to inspect and load models on demand:
  - GET  /api/v0/models            -> list with `state` (loaded/not-loaded)
  - POST /api/v1/models/load       -> load a model into memory
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)


class LMStudioError(Exception):
    """Base error for LM Studio client problems."""


class LMStudioConnectionError(LMStudioError):
    """Raised when the server cannot be reached."""


class LMStudioAPIError(LMStudioError):
    """Raised when the server returns a non-OK response."""


class LMStudioNotSupportedError(LMStudioError):
    """Raised when an endpoint is missing (older LM Studio build)."""


class LMStudioClient:
    """Minimal client for LM Studio's OpenAI-compatible + native endpoints."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        port: int,
        *,
        use_https: bool = False,
        api_key: str | None = None,
        timeout: int = 90,
    ) -> None:
        """Initialize the client."""
        scheme = "https" if use_https else "http"
        self._root = f"{scheme}://{host}:{port}"
        self._openai = f"{self._root}/v1"
        self._session = session
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._headers = {
            "Content-Type": "application/json",
            # LM Studio ignores the value but reverse proxies may require it.
            "Authorization": f"Bearer {api_key or 'lm-studio'}",
        }

    # ---- inference -------------------------------------------------------

    async def async_list_models(self) -> list[str]:
        """Return model identifiers from the OpenAI-compatible endpoint."""
        url = f"{self._openai}/models"
        payload = await self._get(url)
        return [item["id"] for item in payload.get("data", []) if "id" in item]

    async def async_chat_completion(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        """Call /v1/chat/completions and return the parsed JSON payload."""
        url = f"{self._openai}/chat/completions"
        body: dict[str, Any] = {
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        if model:
            body["model"] = model
        return await self._post(url, body)

    # ---- model management ------------------------------------------------

    async def async_models_status(self) -> dict[str, str]:
        """Return {model_id: state} from the native /api/v0/models endpoint.

        Returns an empty dict if the native endpoint is unavailable.
        """
        url = f"{self._root}/api/v0/models"
        try:
            payload = await self._get(url)
        except LMStudioNotSupportedError:
            return {}
        return {
            item["id"]: item.get("state", "unknown")
            for item in payload.get("data", payload if isinstance(payload, list) else [])
            if isinstance(item, dict) and "id" in item
        }

    async def async_load_model(
        self, model: str, *, context_length: int | None = None
    ) -> dict[str, Any]:
        """Load a model into memory via POST /api/v1/models/load."""
        url = f"{self._root}/api/v1/models/load"
        body: dict[str, Any] = {"model": model}
        if context_length:
            body["context_length"] = context_length
        return await self._post(url, body)

    async def async_ensure_loaded(
        self, model: str, *, context_length: int | None = None
    ) -> dict[str, Any]:
        """Make sure `model` is loaded; load it if necessary.

        Falls back gracefully (returns {"status": "jit"}) on older builds that
        lack the native model-management endpoints, where the chat request will
        trigger just-in-time loading anyway.
        """
        status = await self.async_models_status()
        if status.get(model) == "loaded":
            return {"status": "already-loaded", "model": model}
        try:
            result = await self.async_load_model(model, context_length=context_length)
            result.setdefault("status", "loaded")
            return result
        except LMStudioNotSupportedError:
            _LOGGER.debug("Native load endpoint missing; relying on JIT loading")
            return {"status": "jit", "model": model}

    # ---- helpers ---------------------------------------------------------

    async def _get(self, url: str) -> Any:
        try:
            async with self._session.get(
                url, headers=self._headers, timeout=self._timeout
            ) as resp:
                if resp.status == 404:
                    raise LMStudioNotSupportedError(f"404 at {url}")
                text = await resp.text()
                if resp.status != 200:
                    raise LMStudioAPIError(f"GET {url} -> {resp.status}: {text[:300]}")
                return await resp.json()
        except aiohttp.ClientError as err:
            raise LMStudioConnectionError(str(err)) from err

    async def _post(self, url: str, body: dict[str, Any]) -> Any:
        try:
            async with self._session.post(
                url, headers=self._headers, json=body, timeout=self._timeout
            ) as resp:
                if resp.status == 404:
                    raise LMStudioNotSupportedError(f"404 at {url}")
                text = await resp.text()
                if resp.status != 200:
                    raise LMStudioAPIError(f"POST {url} -> {resp.status}: {text[:300]}")
                return await resp.json()
        except aiohttp.ClientError as err:
            raise LMStudioConnectionError(str(err)) from err

    @staticmethod
    def extract_text(payload: dict[str, Any]) -> str:
        """Pull the assistant text out of a chat-completions payload."""
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as err:
            raise LMStudioAPIError(f"Unexpected response shape: {payload}") from err

        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = [
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            ]
            return "".join(parts).strip()
        return str(content).strip()
