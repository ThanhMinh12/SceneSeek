---
title: SceneSeek
emoji: 🎬
colorFrom: gray
colorTo: blue
sdk: gradio
sdk_version: 6.30.0
python_version: 3.12.12
app_file: hf_space/app.py
startup_duration_timeout: 30m
suggested_hardware: zero-a10g
short_description: Find video moments with text, an image, or a reference clip.
---

# SceneSeek · free demo

Real CLIP embeddings and the project's C++20 similarity/sequence matcher.
Upload up to three videos (60 seconds / 40 MB each) per browser session.
Text and image searches return moments; clip searches also estimate playback rate.

This is a **Gradio demonstration**, not the full React/FastAPI deployment.
The original full-stack application and its CPU lock are preserved in
[the source repository](https://github.com/ThanhMinh12/SceneSeek).

ZeroGPU has queues and daily visitor quotas. No paid hardware or credits are
required. Sessions expire after an hour or a restart. Use only non-sensitive
media: Gradio download/preview URLs are shareable capability links, not the
authenticated media routes of the full-stack app. Clearing a library removes
its working files; cached previews may remain for up to an hour.

## Reproduce

Upload `hf_space/README.md`, `hf_space/requirements.txt`, and
`hf_space/packages.txt` to the Space root as `README.md`, `requirements.txt`,
and `packages.txt`. Include `hf_space/*.py`, `backend/sceneseek/*.py`,
`cpp/`, and `CMakeLists.txt`. Do not upload local data, secrets, models, or builds.
Select **ZeroGPU**, never a paid accelerator. The app compiles its small C++
library during startup and downloads the pinned public CLIP checkpoint.

For a local CPU smoke test (not ZeroGPU performance): install the hosted
requirements with a CPU PyTorch wheel, then run
`SCENESEEK_SPACE_DEVICE=cpu python hf_space/app.py` from the repository root.
