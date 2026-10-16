# Release verification — October 16, 2026

Verified for local/portfolio use. This is a bounded, single-process video library,
not a claim of unrestricted multi-tenant production readiness.

## Fixed

- Physical clip rates now use **seconds**, accounting for query/index sampling
  intervals. Absolute frame sampling avoids cumulative drift at 25 fps / 0.5 s.
- Robust temporal matching tolerates up to 25% low-similarity samples (for
  codec/shot-cut outliers), while preserving ordered matching of the remainder.
  Python/C++ rounding and scoring semantics match. Native assertions stay active
  in Release tests.
- Per-shard retrieval and a bounded LRU cache replace whole-library matrix
  concatenation. Real model identity includes a pinned Hugging Face revision.
- FFmpeg creates a silent VP8/WebM derivative; the original is retained. Video
  playback is no longer dependent on the uploaded codec being browser-supported.
- Signed-session ownership covers catalogs, jobs, search, thumbnails, streams,
  and deletion. Cross-origin writes are checked. Indexing/search concurrency,
  upload sizes, duration, resolution, and storage thresholds are bounded.
- Query model work runs off the event loop. Active indexing cannot be deleted.
  Interrupted jobs are marked failed on restart, not left in a fake running state.

## Evidence

- **26 Python tests passed** across both native and NumPy paths; the native
  Release executable also passed. Includes six speed hypotheses, sampling drift,
  rounding/outlier parity, session isolation and cross-origin denial.
- Actual PyTorch CLIP + C++ indexed the first 30 seconds of the official
  [Big Buck Bunny trailer](https://download.blender.org/peach/trailer/trailer_400p.ogg).
  Text retrieval returned real results. An image extracted at **12 s** returned
  **12 s**, cosine similarity about **0.99785**.
- A reference from **10–18 s** matched **10–18 s at 1×**. A half-speed copy
  matched **10–17.98 s at 0.5×**; a double-speed copy matched
  **10–18.08 s at 2×**. These are regression fixtures, not a broad retrieval
  quality benchmark. Static/repetitive scenes and unsearched or variable speeds
  can still be ambiguous.
- Chromium played the actual **30-second WebM** result with no media error.
  Range streaming returned 206; another session could not access the media.
- Synthetic native throughput: **100,000 × 512 float32 vectors**, 195.31 MiB,
  five timed queries, **123.38 ms median** (100.49–232.19 ms observed). This
  excludes model inference, index I/O and HTTP; it is not end-to-end latency or
  a p99 result. Reproduce with `scripts/benchmark_native.py`.
- The installed frozen runtime passes dependency compatibility checks. Model
  revision defaults to `3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268`.

## Deployment limits

Retain `/data` and the model-cache volume, use one API process, and configure
HTTPS / secure cookies. Browser-session isolation is not account login; use
authenticated proxy access for private collections. More than one API replica
requires a shared durable queue/catalog/storage design. Malware scanning,
account identity, automated retention and a larger benchmark remain production
follow-ups; no universal matching or accuracy guarantee is made.

No new AWS resources were provisioned. The existing 512 MB Detour preview
cannot fit the real CLIP worker (over 1 GB observed) or supply durable media
storage. Hosting is pending suitable authorized capacity. Source is public at
[ThanhMinh12/SceneSeek](https://github.com/ThanhMinh12/SceneSeek), and the portfolio
links to it without claiming a hosted demo exists.

Python/native tests and the React build pass in GitHub Actions. Container builds
and non-root startup checks run there because Docker Desktop is unavailable in
this WSL environment; inspect the linked workflow before claiming a particular
container check has passed.

## Reproduce

Build the C++ core, install `backend/requirements.lock` with frozen `--no-deps`
installation, install `backend/requirements-dev.txt` for tests, and run pytest.
The real regression script additionally needs httpx and optional Playwright.
Its docstring lists the real video/image/clip fixtures and expected timestamps;
the model is never substituted with deterministic predictions in that script.
