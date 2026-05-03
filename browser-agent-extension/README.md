# FillNinja browser extension

Chrome **Manifest V3** extension (popup, service worker, content script). Targets the FillNinja API at `http://127.0.0.1:8000`.

## Install

1. From the **repository root** (parent of this folder), start the API as described in **`../README.md`** (**Run the agent API**).
2. Open **`chrome://extensions`**, enable **Developer mode**.
3. **Load unpacked** → choose **this folder** (the one that contains `manifest.json`).
4. Use **Reload** on the extension card after you edit files or run `git pull`.

Full steps, environment variables, and usage: **`../README.md`** → **Install the Chrome extension** and **Use it**.
