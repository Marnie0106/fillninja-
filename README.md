# FillNinja

Browser extension (Manifest V3) that connects a live tab to an AG2 agent backend for form-aware automation.

## Contents

- `browser-agent-extension/` — Chrome extension (popup, service worker, content script).
- `fillninja-pitch-deck.html` — Single-file pitch deck (open in a browser).

## Backend

The extension expects a local API (default `http://localhost:8000`) with endpoints such as `/health`, `POST /agent/run`, SSE `/agent/{taskId}/events`, and action result callbacks. Implement your AG2/FastAPI server separately.

## Extension load

In Chrome: **Extensions → Developer mode → Load unpacked** → select `browser-agent-extension/`.
