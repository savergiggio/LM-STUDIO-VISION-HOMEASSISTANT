"""LM Studio Vision integration for Home Assistant.

Analyze camera snapshots, local image files or image URLs with a vision model
served by a local LM Studio instance. Adds:
  - auto-load of the target model before analysis (native model-management API)
  - event memory + a timeline (calendar + sensor) of remembered analyses
"""

from __future__ import annotations

import base64
import io
import logging
import os
from typing import Any

import voluptuous as vol

from homeassistant.components import camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .api import (
    LMStudioAPIError,
    LMStudioClient,
    LMStudioConnectionError,
)
from .const import (
    ATTR_AFTER,
    ATTR_ALL,
    ATTR_AUTO_LOAD,
    ATTR_BEFORE,
    ATTR_CAMERA,
    ATTR_CONTEXT_LENGTH,
    ATTR_COUNT,
    ATTR_DETAIL,
    ATTR_EVENT_ID,
    ATTR_IMAGE_ENTITY,
    ATTR_IMAGE_FILE,
    ATTR_IMAGE_URL,
    ATTR_LABELS,
    ATTR_MAX_TOKENS,
    ATTR_MEMORY_COUNT,
    ATTR_MODEL,
    ATTR_PROMPT,
    ATTR_QUERY,
    ATTR_REMEMBER,
    ATTR_SUMMARY,
    ATTR_SYSTEM_PROMPT,
    ATTR_TARGET_WIDTH,
    ATTR_TEMPERATURE,
    ATTR_TITLE,
    ATTR_USE_MEMORY,
    CONF_API_KEY,
    CONF_AUTO_LOAD,
    CONF_CONTEXT_LENGTH,
    CONF_HOST,
    CONF_HTTPS,
    CONF_MODEL,
    CONF_PORT,
    CONF_TIMEOUT,
    DEFAULT_AUTO_LOAD,
    DEFAULT_MAX_TOKENS,
    DEFAULT_TARGET_WIDTH,
    DEFAULT_TEMPERATURE,
    DEFAULT_TIMEOUT,
    DOMAIN,
    KEYFRAME_DIR,
    SERVICE_ANALYZE,
    SERVICE_FORGET,
    SERVICE_LIST_MODELS,
    SERVICE_RECALL,
    SERVICE_REMEMBER,
)
from .store import EventStore

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.CALENDAR, Platform.SENSOR]

ANALYZE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PROMPT): cv.string,
        vol.Optional(ATTR_SYSTEM_PROMPT): cv.string,
        vol.Optional(ATTR_IMAGE_ENTITY, default=list): vol.All(
            cv.ensure_list, [cv.entity_id]
        ),
        vol.Optional(ATTR_IMAGE_FILE, default=list): vol.All(
            cv.ensure_list, [cv.string]
        ),
        vol.Optional(ATTR_IMAGE_URL, default=list): vol.All(
            cv.ensure_list, [cv.string]
        ),
        vol.Optional(ATTR_MODEL): cv.string,
        vol.Optional(ATTR_MAX_TOKENS, default=DEFAULT_MAX_TOKENS): cv.positive_int,
        vol.Optional(ATTR_TEMPERATURE, default=DEFAULT_TEMPERATURE): vol.All(
            vol.Coerce(float), vol.Range(min=0, max=2)
        ),
        vol.Optional(ATTR_TARGET_WIDTH, default=DEFAULT_TARGET_WIDTH): vol.All(
            cv.positive_int, vol.Range(min=64, max=4096)
        ),
        vol.Optional(ATTR_DETAIL, default="auto"): vol.In(["auto", "low", "high"]),
        # auto-load
        vol.Optional(ATTR_AUTO_LOAD): cv.boolean,
        vol.Optional(ATTR_CONTEXT_LENGTH): cv.positive_int,
        # event memory
        vol.Optional(ATTR_REMEMBER, default=False): cv.boolean,
        vol.Optional(ATTR_TITLE): cv.string,
        vol.Optional(ATTR_LABELS, default=list): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(ATTR_USE_MEMORY, default=False): cv.boolean,
        vol.Optional(ATTR_MEMORY_COUNT, default=5): cv.positive_int,
    }
)

REMEMBER_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_TITLE): cv.string,
        vol.Required(ATTR_SUMMARY): cv.string,
        vol.Optional(ATTR_CAMERA): cv.string,
        vol.Optional(ATTR_LABELS, default=list): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(ATTR_IMAGE_ENTITY): cv.entity_id,
        vol.Optional(ATTR_TARGET_WIDTH, default=DEFAULT_TARGET_WIDTH): cv.positive_int,
    }
)

RECALL_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_COUNT, default=10): cv.positive_int,
        vol.Optional(ATTR_CAMERA): cv.string,
        vol.Optional(ATTR_AFTER): cv.datetime,
        vol.Optional(ATTR_BEFORE): cv.datetime,
        vol.Optional(ATTR_QUERY): cv.string,
    }
)

FORGET_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_EVENT_ID): cv.string,
        vol.Optional(ATTR_ALL, default=False): cv.boolean,
    }
)


# --------------------------------------------------------------------------- #
# Image helpers
# --------------------------------------------------------------------------- #
def _build_client(
    hass: HomeAssistant, entry: ConfigEntry
) -> tuple[LMStudioClient, dict[str, Any]]:
    """Construct an LMStudioClient + resolved config from a config entry."""
    data = {**entry.data, **entry.options}
    client = LMStudioClient(
        async_get_clientsession(hass),
        host=data[CONF_HOST],
        port=data[CONF_PORT],
        use_https=data.get(CONF_HTTPS, False),
        api_key=data.get(CONF_API_KEY),
        timeout=data.get(CONF_TIMEOUT, DEFAULT_TIMEOUT),
    )
    cfg = {
        "default_model": data.get(CONF_MODEL) or None,
        "auto_load": data.get(CONF_AUTO_LOAD, DEFAULT_AUTO_LOAD),
        "context_length": data.get(CONF_CONTEXT_LENGTH),
    }
    return client, cfg


def _resize_jpeg(raw: bytes, content_type: str, target_width: int) -> tuple[bytes, str]:
    """Best-effort downscale to target_width. Returns (bytes, mime)."""
    try:
        from PIL import Image  # Pillow ships with Home Assistant core.
    except ImportError:  # pragma: no cover
        return raw, content_type or "image/jpeg"

    try:
        with Image.open(io.BytesIO(raw)) as img:
            img = img.convert("RGB")
            if img.width > target_width:
                ratio = target_width / float(img.width)
                img = img.resize(
                    (target_width, max(1, int(img.height * ratio))), Image.LANCZOS
                )
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=85)
            return out.getvalue(), "image/jpeg"
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Image resize skipped (%s)", err)
        return raw, content_type or "image/jpeg"


def _to_data_url(raw: bytes, mime: str) -> str:
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{b64}"


async def _snapshot_camera(
    hass: HomeAssistant, entity_id: str, target_width: int
) -> tuple[bytes, str]:
    """Return resized JPEG bytes for a camera entity."""
    try:
        image = await camera.async_get_image(hass, entity_id)
    except HomeAssistantError as err:
        raise ServiceValidationError(
            f"Cannot grab snapshot from {entity_id}: {err}"
        ) from err
    return await hass.async_add_executor_job(
        _resize_jpeg, image.content, image.content_type, target_width
    )


async def _collect_images(
    hass: HomeAssistant, call: ServiceCall, target_width: int, detail: str
) -> tuple[list[dict[str, Any]], tuple[bytes, str] | None, str | None]:
    """Gather images into content parts.

    Returns (parts, keyframe, source_camera) where keyframe is the first image
    (resized JPEG bytes + mime), used as the timeline thumbnail.
    """
    parts: list[dict[str, Any]] = []
    keyframe: tuple[bytes, str] | None = None
    source_camera: str | None = None
    session = async_get_clientsession(hass)

    def _add(raw: bytes, mime: str) -> None:
        nonlocal keyframe
        if keyframe is None:
            keyframe = (raw, mime)
        parts.append(
            {
                "type": "image_url",
                "image_url": {"url": _to_data_url(raw, mime), "detail": detail},
            }
        )

    for entity_id in call.data.get(ATTR_IMAGE_ENTITY, []):
        if source_camera is None:
            source_camera = entity_id
        raw, mime = await _snapshot_camera(hass, entity_id, target_width)
        _add(raw, mime)

    for path in call.data.get(ATTR_IMAGE_FILE, []):
        if not hass.config.is_allowed_path(path):
            raise ServiceValidationError(
                f"Path {path} is not allowed. Add its folder to "
                "homeassistant -> allowlist_external_dirs in configuration.yaml."
            )

        def _read(p: str = path) -> bytes:
            with open(p, "rb") as handle:
                return handle.read()

        try:
            raw = await hass.async_add_executor_job(_read)
        except OSError as err:
            raise ServiceValidationError(f"Cannot read {path}: {err}") from err
        raw, mime = await hass.async_add_executor_job(
            _resize_jpeg, raw, "image/jpeg", target_width
        )
        _add(raw, mime)

    for url in call.data.get(ATTR_IMAGE_URL, []):
        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    raise ServiceValidationError(
                        f"Image URL {url} returned HTTP {resp.status}"
                    )
                raw = await resp.read()
                mime = resp.headers.get("Content-Type", "image/jpeg").split(";")[0]
        except ServiceValidationError:
            raise
        except Exception as err:  # noqa: BLE001
            raise ServiceValidationError(f"Cannot fetch {url}: {err}") from err
        raw, mime = await hass.async_add_executor_job(
            _resize_jpeg, raw, mime, target_width
        )
        _add(raw, mime)

    if not parts:
        raise ServiceValidationError(
            "No image provided. Pass at least one of image_entity, "
            "image_file or image_url."
        )
    return parts, keyframe, source_camera


async def _save_keyframe(
    hass: HomeAssistant, event_id: str, raw: bytes
) -> tuple[str, str]:
    """Persist a keyframe under <config>/www and return (path, web_url)."""
    folder = hass.config.path("www", KEYFRAME_DIR)
    path = os.path.join(folder, f"{event_id}.jpg")

    def _write() -> None:
        os.makedirs(folder, exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(raw)

    await hass.async_add_executor_job(_write)
    return path, f"/local/{KEYFRAME_DIR}/{event_id}.jpg"


# --------------------------------------------------------------------------- #
# Setup
# --------------------------------------------------------------------------- #
async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up LM Studio Vision from a config entry."""
    domain_data = hass.data.setdefault(DOMAIN, {})

    if "_store" not in domain_data:
        store = EventStore(hass)
        await store.async_load()
        domain_data["_store"] = store

    domain_data[entry.entry_id] = entry

    # Only the first entry "owns" the shared timeline entities.
    if "_owner" not in domain_data:
        domain_data["_owner"] = entry.entry_id
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _register_services(hass)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


def _register_services(hass: HomeAssistant) -> None:
    """Register all services once."""
    if hass.services.has_service(DOMAIN, SERVICE_ANALYZE):
        return

    domain_data = hass.data[DOMAIN]
    store: EventStore = domain_data["_store"]

    def _resolve_entry() -> ConfigEntry:
        loaded = [
            e
            for e in hass.config_entries.async_entries(DOMAIN)
            if e.entry_id in domain_data
        ]
        if not loaded:
            raise HomeAssistantError("LM Studio Vision is not configured.")
        return loaded[0]

    async def handle_analyze(call: ServiceCall) -> ServiceResponse:
        client, cfg = _build_client(hass, _resolve_entry())

        parts, keyframe, source_camera = await _collect_images(
            hass,
            call,
            target_width=call.data[ATTR_TARGET_WIDTH],
            detail=call.data[ATTR_DETAIL],
        )

        model = call.data.get(ATTR_MODEL) or cfg["default_model"]

        # --- auto-load -------------------------------------------------- #
        auto_load = call.data.get(ATTR_AUTO_LOAD)
        if auto_load is None:
            auto_load = cfg["auto_load"]
        load_status: dict[str, Any] | None = None
        if auto_load and model:
            ctx = call.data.get(ATTR_CONTEXT_LENGTH) or cfg["context_length"]
            try:
                load_status = await client.async_ensure_loaded(
                    model, context_length=ctx
                )
            except LMStudioConnectionError as err:
                raise HomeAssistantError(
                    f"Cannot reach LM Studio. Is the server running? ({err})"
                ) from err
            except LMStudioAPIError as err:
                # Don't abort the analysis: chat will JIT-load or fail clearly.
                _LOGGER.warning("Auto-load of %s failed: %s", model, err)

        # --- build messages -------------------------------------------- #
        messages: list[dict[str, Any]] = []
        if call.data.get(ATTR_USE_MEMORY):
            recent = store.query(count=call.data[ATTR_MEMORY_COUNT])
            if recent:
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            "Recent observed events for context (oldest first). "
                            "Use only if relevant:\n"
                            + EventStore.as_log_text(recent)
                        ),
                    }
                )
        if system_prompt := call.data.get(ATTR_SYSTEM_PROMPT):
            messages.append({"role": "system", "content": system_prompt})
        messages.append(
            {
                "role": "user",
                "content": [{"type": "text", "text": call.data[ATTR_PROMPT]}, *parts],
            }
        )

        # --- inference -------------------------------------------------- #
        try:
            payload = await client.async_chat_completion(
                messages=messages,
                model=model,
                max_tokens=call.data[ATTR_MAX_TOKENS],
                temperature=call.data[ATTR_TEMPERATURE],
            )
            text = LMStudioClient.extract_text(payload)
        except LMStudioConnectionError as err:
            raise HomeAssistantError(
                f"Cannot reach LM Studio. Is the server running? ({err})"
            ) from err
        except LMStudioAPIError as err:
            raise HomeAssistantError(f"LM Studio API error: {err}") from err

        result: dict[str, Any] = {
            "response_text": text,
            "model": payload.get("model", model),
            "images": len(parts),
            "usage": payload.get("usage", {}),
        }
        if load_status:
            result["load_status"] = load_status.get("status")

        # --- remember --------------------------------------------------- #
        if call.data.get(ATTR_REMEMBER):
            title = call.data.get(ATTR_TITLE) or (
                text[:60] + ("…" if len(text) > 60 else "")
            )
            image_path = image_url = None
            if keyframe is not None:
                # event id is generated inside the store; pre-generate via add.
                import uuid

                event_id = uuid.uuid4().hex
                image_path, image_url = await _save_keyframe(
                    hass, event_id, keyframe[0]
                )
                event = await store.async_add(
                    title=title,
                    summary=text,
                    camera=source_camera,
                    model=result["model"],
                    prompt=call.data[ATTR_PROMPT],
                    labels=call.data.get(ATTR_LABELS, []),
                    image_path=image_path,
                    image_url=image_url,
                )
                # rename the saved file to match the real event id for tidiness
                if event["id"] != event_id:
                    new_path, new_url = await _save_keyframe(
                        hass, event["id"], keyframe[0]
                    )
                    event["image_path"], event["image_url"] = new_path, new_url
            else:
                event = await store.async_add(
                    title=title,
                    summary=text,
                    camera=source_camera,
                    model=result["model"],
                    prompt=call.data[ATTR_PROMPT],
                    labels=call.data.get(ATTR_LABELS, []),
                )
            result["event_id"] = event["id"]
            result["remembered"] = True

        return result

    async def handle_list_models(call: ServiceCall) -> ServiceResponse:
        client, _ = _build_client(hass, _resolve_entry())
        try:
            models = await client.async_list_models()
            status = await client.async_models_status()
        except LMStudioConnectionError as err:
            raise HomeAssistantError(f"Cannot reach LM Studio: {err}") from err
        return {
            "models": models,
            "loaded": [m for m, s in status.items() if s == "loaded"],
            "status": status,
        }

    async def handle_remember(call: ServiceCall) -> ServiceResponse:
        image_path = image_url = None
        if entity_id := call.data.get(ATTR_IMAGE_ENTITY):
            raw, _ = await _snapshot_camera(
                hass, entity_id, call.data[ATTR_TARGET_WIDTH]
            )
            import uuid

            event_id = uuid.uuid4().hex
            image_path, image_url = await _save_keyframe(hass, event_id, raw)
        event = await store.async_add(
            title=call.data[ATTR_TITLE],
            summary=call.data[ATTR_SUMMARY],
            camera=call.data.get(ATTR_CAMERA) or call.data.get(ATTR_IMAGE_ENTITY),
            labels=call.data.get(ATTR_LABELS, []),
            image_path=image_path,
            image_url=image_url,
        )
        return {"event_id": event["id"], "remembered": True}

    async def handle_recall(call: ServiceCall) -> ServiceResponse:
        after = call.data.get(ATTR_AFTER)
        before = call.data.get(ATTR_BEFORE)
        if after and after.tzinfo is None:
            after = dt_util.as_local(after)
        if before and before.tzinfo is None:
            before = dt_util.as_local(before)
        events = store.query(
            count=call.data[ATTR_COUNT],
            camera=call.data.get(ATTR_CAMERA),
            after=after,
            before=before,
            text=call.data.get(ATTR_QUERY),
        )
        return {
            "events": events,
            "count": len(events),
            "text": EventStore.as_log_text(events),
        }

    async def handle_forget(call: ServiceCall) -> ServiceResponse:
        if call.data.get(ATTR_ALL):
            cleared = await store.async_clear()
            return {"cleared": cleared}
        event_id = call.data.get(ATTR_EVENT_ID)
        if not event_id:
            raise ServiceValidationError("Provide event_id or set all: true.")
        removed = await store.async_remove(event_id)
        return {"removed": removed}

    hass.services.async_register(
        DOMAIN, SERVICE_ANALYZE, handle_analyze,
        schema=ANALYZE_SCHEMA, supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_LIST_MODELS, handle_list_models,
        schema=vol.Schema({}), supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_REMEMBER, handle_remember,
        schema=REMEMBER_SCHEMA, supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_RECALL, handle_recall,
        schema=RECALL_SCHEMA, supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_FORGET, handle_forget,
        schema=FORGET_SCHEMA, supports_response=SupportsResponse.OPTIONAL,
    )


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry and clean up when the last one goes away."""
    domain_data = hass.data.get(DOMAIN, {})

    if domain_data.get("_owner") == entry.entry_id:
        await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
        domain_data.pop("_owner", None)
        domain_data.pop("_calendar_added", None)
        domain_data.pop("_sensor_added", None)

    domain_data.pop(entry.entry_id, None)

    remaining = [
        k for k in domain_data if not k.startswith("_")
    ]
    if not remaining:
        for service in (
            SERVICE_ANALYZE,
            SERVICE_LIST_MODELS,
            SERVICE_REMEMBER,
            SERVICE_RECALL,
            SERVICE_FORGET,
        ):
            if hass.services.has_service(DOMAIN, service):
                hass.services.async_remove(DOMAIN, service)
        domain_data.pop("_store", None)

    return True
