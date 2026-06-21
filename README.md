# LM-STUDIO-VISION-HOMEASSISTANT
A LM-Studio addon for HomeAssistant - A Visual intelligence for your home.

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Validate](https://github.com/savergiggio/LM-STUDIO-VISION-HOMEASSISTANT/actions/workflows/validate.yml/badge.svg)](https://github.com/savergiggio/LM-STUDIO-VISION-HOMEASSISTANT/actions/workflows/validate.yml)

A custom **integration** that brings *LLM Vision*–style image analysis to Home
Assistant, powered entirely by a **local [LM Studio](https://lmstudio.ai)
server**. It sends camera snapshots, image files or image URLs to a vision model
(VLM) through LM Studio's OpenAI-compatible API and hands the answer back to your
automations.

On top of plain analysis it adds three things:

- **Auto-load** — loads the target model into LM Studio before the request if it
  isn't loaded yet.
- **Event memory** — remembers analyses (with a saved keyframe) and can feed
  recent events back into a prompt for continuity.
- **Timeline** — a Calendar entity and a Sensor that expose remembered events on
  your dashboards.

Everything runs on your LAN. No cloud, no subscription, no API key required.

> **Note on terminology:** this is a Home Assistant *integration* (a
> `custom_components` component), not a Supervisor *add-on*. It therefore works
> on every install type (HA OS, Supervised, Container, Core).

---

## Contents

- [Requirements](#requirements)
- [Installation](#installation)
- [LM Studio setup](#lm-studio-setup)
- [Configuration](#configuration)
- [Services](#services)
- [Entities](#entities)
- [Examples](#examples)
- [Dashboard](#dashboard)
- [Troubleshooting](#troubleshooting)

---

## Requirements

- **LM Studio 0.3.6+** with the local server running.
  Auto-load uses the native `POST /api/v1/models/load` endpoint (**0.4.0+**); on
  older builds it falls back to just-in-time loading automatically.
- A **vision model** available in LM Studio — e.g. Qwen2-VL, Pixtral, a LLaVA /
  MiniCPM-V / InternVL build. Text-only models will reject images.
- **Home Assistant 2024.10** or newer.

---

## Installation

### Option A — HACS (recommended)

1. Make sure [HACS](https://hacs.xyz) is installed.
2. In Home Assistant go to **HACS → ⋮ (top-right) → Custom repositories**.
3. Add the repository URL
   `https://github.com/savergiggio/LM-STUDIO-VISION-HOMEASSISTANT`
   and choose category **Integration**, then **Add**.
4. Open the new *LM Studio Vision* card, click **Download**, and **restart Home
   Assistant**.

### Option B — Manual

1. Copy the `custom_components/lmstudio_vision` folder from this repo into your
   Home Assistant `config/custom_components/` directory.
   The result must be `config/custom_components/lmstudio_vision/manifest.json`.
2. Restart Home Assistant.

### Add the integration

After restarting, go to **Settings → Devices & Services → Add Integration**,
search for **LM Studio Vision**, and fill in the connection form (see
[Configuration](#configuration)).

---

## LM Studio setup

1. Open LM Studio and go to the **Developer** tab.
2. **Start Server** (default port `1234`). To reach it from another machine,
   set the server to listen on `0.0.0.0` and use that machine's LAN IP in the
   integration.
3. **Download and load a vision model** (look for models tagged as *Vision* /
   `vlm`). If you enable **Just-In-Time model loading** in the server settings,
   the integration's auto-load (and LM Studio itself) can load models on demand.
4. *(Optional)* If you put LM Studio behind authentication, generate an **API
   token** on the Developer page and enter it in the integration's *API key*
   field.

---

## Configuration

All configuration is done through the UI (config flow). No YAML required.

### Setup form

| Field | Default | Description |
|-------|---------|-------------|
| **Host** | `localhost` | Hostname/IP of the LM Studio server. |
| **Port** | `1234` | LM Studio server port. |
| **Use HTTPS** | off | Enable if LM Studio is behind an HTTPS proxy. |
| **API key** | empty | Bearer token, only if your server requires one. |
| **Default model** | empty | Model identifier to use when a service call doesn't specify one. Empty = use whatever model is currently loaded. |
| **Auto-load model** | on | Load the target model before each analysis if it isn't loaded. |
| **Context length** | `0` | Context length to request when loading a model. `0` = let LM Studio decide. |
| **Request timeout** | `90` | Per-request timeout in seconds (raise it for slow cold starts). |

### Options (after setup)

Open the integration → **Configure** to change the **default model**,
**auto-load**, **context length**, **timeout** and **API key** at any time. The
integration reloads automatically when you save.

Tip: run the `lmstudio_vision.list_models` service once to discover the exact
model identifiers and see which ones are currently loaded.

---

## Services

### `lmstudio_vision.analyze`

Send one or more images plus a prompt to the model and return its text.

Returns a response object (use `response_variable`):
`response_text`, `model`, `images`, `usage`, plus `load_status` (when auto-load
ran) and `event_id` / `remembered` (when `remember: true`).

| Field | Req. | Notes |
|-------|------|-------|
| `prompt` | ✅ | The question/instruction. |
| `system_prompt` | | Steers tone/format. |
| `image_entity` | ◻️ | One or more `camera.*` entities (snapshotted). |
| `image_file` | ◻️ | Absolute paths; folder must be in `allowlist_external_dirs`. |
| `image_url` | ◻️ | Image URLs to fetch and inline. |
| `model` | | Empty = currently loaded model. |
| `auto_load` | | Override the per-integration default for this call. |
| `context_length` | | Context length when loading. |
| `max_tokens` | | Default `4096`. |
| `temperature` | | Default `0.2`. |
| `target_width` | | Downscale wide images before sending. Default `1280`. |
| `detail` | | `auto` / `low` / `high`. |
| `use_memory` | | Inject recent remembered events as context. |
| `memory_count` | | How many recent events to inject (default `5`). |
| `remember` | | Store the result on the timeline (with a keyframe). |
| `title` | | Title for the remembered event. |
| `labels` | | Optional tags for the remembered event. |
| `response` | | Optional response variable. |


### `lmstudio_vision.list_models`

Returns `{ models, loaded, status }` — all known model identifiers, which are
loaded, and the full state map.

### `lmstudio_vision.remember`

Manually add a timeline event: `title`, `summary`, `camera`, `labels`, optional
`image_entity` (snapshotted as the keyframe).

### `lmstudio_vision.recall`

Query event memory: `count`, `camera`, `after`, `before`, `query`. Returns the
matching `events`, a `count`, and a compact `text` log (handy for notifications
or to feed back into a prompt).

### `lmstudio_vision.forget`

`event_id` to delete one event, or `all: true` to clear the whole timeline.

---

## Entities

The integration creates a single **LM Studio Vision** device with:

- **`calendar.lmstudio_vision_timeline`** — every remembered event as a calendar
  event (start = timestamp, summary = title, description = analysis, location =
  camera). Drop it into the native **Calendar** dashboard card.
- **`sensor.lmstudio_vision_last_event`** — state is the latest event title;
  attributes include `count`, `last_summary`, `last_camera`, `last_image`, and a
  `events` list of recent entries for custom cards/templates.

Keyframes are stored at `config/www/lmstudio_vision/<id>.jpg` and served at
`/local/lmstudio_vision/<id>.jpg`.

---

## Examples

### Doorbell → analyze, auto-load, remember, notify

```yaml
automation:
  - alias: Doorbell smart description
    trigger:
      - platform: state
        entity_id: binary_sensor.front_door_motion
        to: "on"
    action:
      - service: lmstudio_vision.analyze
        data:
          image_entity: camera.front_door
          model: qwen2-vl-7b-instruct   # auto-loaded if not already in memory
          auto_load: true
          system_prompt: "You are a concise security assistant."
          prompt: "Describe who or what is at the door in one sentence."
          max_tokens: 100
          remember: true
          title: "Front door"
        response_variable: vision
      - service: notify.mobile_app_phone
        data:
          title: "Front door"
          message: "{{ vision.response_text }}"
```

### Use event memory for continuity

```yaml
service: lmstudio_vision.analyze
data:
  image_entity: camera.driveway
  prompt: "Has anything changed compared to the recent events?"
  use_memory: true
  memory_count: 5
  remember: true
response_variable: vision
```

### Recall the last events into a notification

```yaml
service: lmstudio_vision.recall
data:
  count: 5
  camera: camera.front_door
response_variable: history
# history.text is a ready-to-send chronological log
```

---

## Dashboard

Timeline card:

```yaml
type: calendar
entities:
  - calendar.lmstudio_vision_timeline
```

Latest event with thumbnail:

```yaml
type: markdown
content: >
  **{{ states('sensor.lmstudio_vision_last_event') }}**

  {{ state_attr('sensor.lmstudio_vision_last_event','last_summary') }}

  ![keyframe]({{ state_attr('sensor.lmstudio_vision_last_event','last_image') }})
```

---

## Troubleshooting

- **"Cannot reach LM Studio"** — the server isn't running or host/port are
  wrong. Confirm the Developer → Start Server toggle, and that the port is
  reachable from the HA host (firewall / `0.0.0.0` binding for remote servers).
- **The model returns nonsense or ignores the image** — the loaded model is not
  a vision model. Load a VLM and/or set `model` to its identifier.
- **First call is very slow / times out** — the model is warming up. Increase
  the **Request timeout** in the options.
- **`Path ... is not allowed`** — add the file's folder to
  `homeassistant: allowlist_external_dirs:` in `configuration.yaml`.
- **Auto-load doesn't seem to do anything** — auto-load only runs when a model
  is known (per-call `model` or the default in options). With no model set it
  relies on whatever is currently loaded / JIT loading.

---

## License

[MIT](LICENSE)

## Disclaimer

Not affiliated with LM Studio or the Home Assistant project. "LM Studio" is a
trademark of its respective owner.
