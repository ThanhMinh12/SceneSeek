---
title: SceneSeek
emoji: 🎬
colorFrom: gray
colorTo: blue
sdk: gradio
sdk_version: 6.30.0
python_version: 3.12.12
app_file: hf_space/fullstack.py
startup_duration_timeout: 30m
suggested_hardware: zero-a10g
short_description: Find video moments with text, an image, or a reference clip.
---

# SceneSeek · free demo

Real CLIP embeddings and the project's C++20 similarity/sequence matcher.
Upload up to three videos (60 seconds / 40 MB each) per browser session.
Text and image searches return moments; clip searches also estimate playback rate.

The real **React/TypeScript interface and FastAPI video/job/search/media routes**
run here. Gradio Server mode supplies queued GPU transport, not a replacement
UI. React prepares owned requests over REST and dispatches single-use tokens
through `@gradio/client` to retain visitor quota handling. Media remains behind
the signed-session API. The original CPU/container runtime is preserved in
[the source repository](https://github.com/ThanhMinh12/SceneSeek).

ZeroGPU has queues and daily visitor quotas. No paid hardware or credits are
required. Finished/failed videos expire after an hour (checked every five
minutes) or are lost on restart. Use only non-sensitive media. API routes enforce
signed browser-session ownership, including inside the HF iframe with secure
partitioned cookies. Delete a video to remove its working files immediately.
Browser-session isolation is not account login; storage is not durable.

## Reproduce

Upload `hf_space/README.md`, `hf_space/requirements.txt`, and
`hf_space/packages.txt` to the Space root as `README.md`, `requirements.txt`,
and `packages.txt`. Include `hf_space/*.py`, `backend/sceneseek/*.py`,
`cpp/`, `CMakeLists.txt`, and compiled `frontend/dist/`. Build the frontend with
`npm ci` and `npm run build` in `frontend/` before uploading those static assets.
Do not upload local data, secrets, models, or native builds.
Select **ZeroGPU**, never a paid accelerator. The app compiles its small C++
library during startup and downloads the pinned public CLIP checkpoint.

For a local CPU smoke test (not ZeroGPU performance): install the hosted
requirements with a CPU PyTorch wheel, then run
`SCENESEEK_SPACE_DEVICE=cpu python hf_space/fullstack.py` from the repository root.

The former widget UI is retained as `hf_space/app.py` for rollback.
