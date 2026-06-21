"""Constants for the LM Studio Vision integration."""

from __future__ import annotations

DOMAIN = "lmstudio_vision"

# Config / options keys
CONF_HOST = "host"
CONF_PORT = "port"
CONF_HTTPS = "https"
CONF_API_KEY = "api_key"
CONF_MODEL = "model"
CONF_TIMEOUT = "timeout"
CONF_AUTO_LOAD = "auto_load"
CONF_CONTEXT_LENGTH = "context_length"

# Defaults
DEFAULT_HOST = "localhost"
DEFAULT_PORT = 1234
DEFAULT_HTTPS = False
DEFAULT_TIMEOUT = 90
DEFAULT_MAX_TOKENS = 512
DEFAULT_TEMPERATURE = 0.2
DEFAULT_TARGET_WIDTH = 1280
DEFAULT_AUTO_LOAD = True

# Services
SERVICE_ANALYZE = "analyze"
SERVICE_LIST_MODELS = "list_models"
SERVICE_REMEMBER = "remember"
SERVICE_RECALL = "recall"
SERVICE_FORGET = "forget"

# Service field names
ATTR_PROMPT = "prompt"
ATTR_IMAGE_ENTITY = "image_entity"
ATTR_IMAGE_FILE = "image_file"
ATTR_IMAGE_URL = "image_url"
ATTR_MODEL = "model"
ATTR_MAX_TOKENS = "max_tokens"
ATTR_TEMPERATURE = "temperature"
ATTR_TARGET_WIDTH = "target_width"
ATTR_DETAIL = "detail"
ATTR_SYSTEM_PROMPT = "system_prompt"
ATTR_AUTO_LOAD = "auto_load"
ATTR_CONTEXT_LENGTH = "context_length"
# event-memory related
ATTR_REMEMBER = "remember"
ATTR_TITLE = "title"
ATTR_SUMMARY = "summary"
ATTR_CAMERA = "camera"
ATTR_LABELS = "labels"
ATTR_USE_MEMORY = "use_memory"
ATTR_MEMORY_COUNT = "memory_count"
ATTR_COUNT = "count"
ATTR_AFTER = "after"
ATTR_BEFORE = "before"
ATTR_QUERY = "query"
ATTR_EVENT_ID = "event_id"
ATTR_ALL = "all"

# Event store / timeline
STORAGE_KEY = f"{DOMAIN}_events"
STORAGE_VERSION = 1
MAX_EVENTS = 500
SIGNAL_EVENTS_UPDATED = f"{DOMAIN}_events_updated"
KEYFRAME_DIR = "lmstudio_vision"  # under <config>/www/
