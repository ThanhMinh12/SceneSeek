# SceneSeek

[![Verify](https://github.com/ThanhMinh12/SceneSeek/actions/workflows/ci.yml/badge.svg)](https://github.com/ThanhMinh12/SceneSeek/actions/workflows/ci.yml)

SceneSeek is a **C++20 video retrieval engine with a Python ML/API adapter** for finding the moment you can
picture but cannot locate. It indexes timestamped video frames into a shared
CLIP embedding space and accepts three kinds of query:

- **Text** — describe visible subjects, actions, environments, colors, or composition.
- **Image** — provide a still image and retrieve visually similar moments.
- **Clip** — provide a short sequence and align it against indexed videos across
  multiple playback-rate hypotheses.

Search results link directly to the matching timestamp. Video ingestion runs in
the background and exposes progress through a job API.

[Try the live demo](https://huggingface.co/spaces/ThanhMinh12/SceneSeek).
The free ZeroGPU deployment runs the actual React/TypeScript interface,
FastAPI library/search/media routes, and real CLIP/C++ pipeline. Gradio Server
mode handles browser-dispatched GPU work behind the React UI. Libraries are
temporary, with up to three 60-second/40 MB videos. Queues and daily limits apply; use only
non-sensitive media. See [hosted setup and limits](hf_space/README.md) and the
[release report](docs/RELEASE-READINESS.md).

## Architecture

```text
React + TypeScript                       Python + FastAPI
┌────────────────────────┐              ┌─────────────────────────────┐
│ upload + job tracking  │   REST       │ upload validation + SQLite │
│ text/image/clip search │─────────────▶│ OpenCV frame sampling       │
│ timestamped preview    │              │ PyTorch CLIP embeddings     │
└────────────────────────┘              └──────────────┬──────────────┘
                                                      │ contiguous float32
                                                      ▼
                                       ┌─────────────────────────────┐
                                       │ C++20 / CMake search engine │
                                       │ mmap indexes + bounded LRU  │
                                       │ parallel ranking + dedup    │
                                       │ timestamp/rate alignment    │
                                       └─────────────────────────────┘
```

The C++ engine owns index serialization, normalized vectors, memory-mapped reads,
a byte-budgeted LRU, bounded parallel shard search, global ranking, temporal
duplicate suppression, and complete timestamp-aware clip matching. Python keeps
CLIP inference, media ingestion, authorization, SQLite, and REST response formatting.
A small `ctypes` C ABI preserves the existing deployment without an extra binding
dependency. NumPy code remains only as an offline fallback/test oracle; the hosted
app and Docker require the full C++ engine. Existing `.npz` indexes migrate lazily
to native `.ssidx` files without deleting the original archives.

See [architecture](docs/ARCHITECTURE.md), [the native format/CLI](docs/NATIVE-ENGINE.md),
and [measured benchmarks](docs/NATIVE-BENCHMARKS.md).

## Standalone C++ tools

The `sceneseek` executable has no Python or model-runtime dependency. It indexes
**precomputed embeddings** and searches native files directly:

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build
build/sceneseek --help
build/sceneseek benchmark 100000 512 10 4 256 2
```

Commands include `index`, `inspect`, `search`, `sequence`, and `benchmark`.
The benchmark reports cold/warm timings, cache configuration, and Linux peak RSS;
it does not measure CLIP inference or retrieval quality.

## Run with Docker

The complete stack—including the React build, native C++ library, FastAPI app,
FFmpeg, and model runtime—ships as one container:

```bash
docker compose up --build
```

Open <http://localhost:8000>. The first real search or index operation downloads
the configured `openai/clip-vit-base-patch32` model into the persistent model
cache. Uploaded videos and indexes live in a separate persistent volume.

CPU inference is supported. Set `SCENESEEK_DEVICE=cuda` and provide a
CUDA-enabled PyTorch image for GPU inference.

## Develop locally

Prerequisites: Python 3.11, Node 22.12+, CMake 3.20+, a C++20 compiler, and FFmpeg.
The frozen CPU runtime is verified on Linux x86-64.

```bash
# Native retrieval core
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build
ctest --test-dir build --output-on-failure

# API
python3.11 -m venv .venv
source .venv/bin/activate
pip install --no-deps -r backend/requirements.lock
SCENESEEK_NATIVE_LIBRARY="$PWD/build/libsceneseek_core.so" \
  PYTHONPATH=backend uvicorn sceneseek.main:app --reload

# Web app, in another shell
cd frontend
npm ci
npm run dev
```

For fast offline development without model downloads, set
`SCENESEEK_EMBEDDER=deterministic`. That backend is deliberately simple and is
not a substitute for CLIP quality.

## API

Interactive OpenAPI documentation is available at `/api/docs`.

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Runtime, model, and native-index status |
| `POST` | `/api/videos` | Upload a video and enqueue indexing |
| `GET` | `/api/jobs/{id}` | Poll indexing progress or failure |
| `GET` | `/api/videos` | List the searchable library |
| `DELETE` | `/api/videos/{id}` | Remove media, thumbnails, and its index |
| `POST` | `/api/search/text` | Search with a natural-language description |
| `POST` | `/api/search/image` | Search with a reference image |
| `POST` | `/api/search/clip` | Align an example clip against indexed sequences |

Example text search:

```bash
curl -X POST http://localhost:8000/api/search/text \
  -H 'Content-Type: application/json' \
  -d '{"query":"a person walking through snow at night","top_k":8}'
```

## Verification

```bash
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build
ctest --test-dir build --output-on-failure

python -m pip install -r backend/requirements-dev.txt
cd backend && python -m pytest

cd frontend && npm install && npm run build
```

The API tests use the deterministic embedder so CI remains reproducible and
does not download model weights. The production container defaults to CLIP.

Real-model regressions are separate: `scripts/smoke_real.py` exercises actual
text/image retrieval, normal/half/double-speed clips, private sessions, and
optional Chromium WebM playback. `scripts/benchmark_native.py` measures native
cosine throughput, not embedding latency or retrieval accuracy. See
[release verification](docs/RELEASE-READINESS.md) for measured results.

## Production notes

- One API process is intentional: in-process background jobs and model memory
  must not be duplicated across workers. A multi-instance deployment should move
  jobs to a durable queue and keep indexes in shared object storage.
- The native catalog performs exact flat search over memory-mapped shards.
  `SCENESEEK_NATIVE_CACHE_MB` (default 64) bounds retained mappings/metadata,
  not total process RSS or model memory. `SCENESEEK_NATIVE_THREADS` (default 2,
  maximum 8) bounds shard parallelism. Larger libraries may need a larger cache
  or an ANN index; benchmark the intended workload rather than assuming a speedup.
- Catalogs, jobs, thumbnails, streams, search, and deletion are isolated by signed
  browser sessions. This is not an account/login system: clearing cookies loses
  access to a library. Keep `/data/.session-secret` persistent and set
  `SCENESEEK_COOKIE_SECURE=true` behind HTTPS. Use reverse-proxy authentication
  for a private deployment with sensitive media.
- Indexing has a two-job queue by default; search concurrency is bounded; media
  duration, resolution, request size, and storage thresholds are enforced.
  FFmpeg creates silent VP8/WebM previews for portable browser playback while
  retaining the original video. Query clips must be 4–60 seconds.
- Playback rates mean source seconds per reference second. Query features are
  resampled onto each index's actual temporal grid. The sequence score drops up
  to the lowest 25% of aligned cosine samples to tolerate codec/shot-cut outliers.
  Scores are not calibrated probabilities, and matching is approximate, not an
  identity guarantee or support for arbitrary variable-speed ramps.

See [deployment options](docs/DEPLOYMENT.md) before exposing the service publicly.

## License

MIT. CLIP model weights and runtime dependencies retain their own licenses.

