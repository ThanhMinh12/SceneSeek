# Release verification — October 16, 2026

## C++ retrieval engine upgrade

Production retrieval now uses an owning C++20 engine, not just two numeric
kernels. C++ manages versioned `.ssidx` serialization, normalized vectors,
checksummed/memory-mapped reads, a byte-budgeted LRU, parallel shard retrieval,
global ranking/deduplication, physical-time query resampling, and sequence fits.
Python retains CLIP inference, media ingestion, session authorization, SQLite,
and REST response formatting. The C ABI is exception-safe and owns its handle;
NumPy is an offline reference path, never a silent production replacement.

Verified locally: four CTest targets in both Release and ASan/UBSan builds,
56 backend tests plus seven hosted-adapter tests, Python/native parity,
authorization and legacy-migration tests, bounded cache/bypass and concurrent
replacement tests. The CLI runs without Python and reports measured retrieval
timings and cache settings; see [benchmarks](NATIVE-BENCHMARKS.md).

A genuine CPU CLIP/API replay with the new native engine returned the source
image at **12.0 s**, and matched the **10.0–18.0 s** reference span at 1x,
**10.0–17.98 s** at .5x, and **10.0–18.08 s** at 2x. Text retrieval returned
results, browser-preview range requests succeeded, and a stranger session
could not access the library or media. The same real-model replay passed in
Chromium through the production React build, playing the 30-second result
without a media error. This is one public Blender trailer
fixture, not a general accuracy or latency claim.

The prior release history below remains for provenance. The native upgrade's
operational details supersede older descriptions of NumPy-owned indexes.

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
storage. The React/FastAPI stack is now configured on the existing free ZeroGPU
Space; durable production storage remains a separate requirement.

The user subsequently authorized free non-AWS hosting. The
[live application](https://huggingface.co/spaces/ThanhMinh12/SceneSeek) runs
on free ZeroGPU (confirmed requested and actual hardware `zero-a10g`, no paid
plan/hardware/credits enabled). The actual React UI and private FastAPI routes
now run through Gradio Server mode, not the former widget interface. The CPU
lock remains intact. The hosted profile uses Python 3.12, PyTorch 2.8 and
Transformers 5.20.1; projected feature extraction supports both Transformers
4 and 5 with regression coverage.

Hosted real-CLIP/C++ API checks passed: 30-second upload/indexing, text search,
image retrieval at **12 s** (cosine **0.9978**), and a double-speed reference
matched **10–18.08 s at 2×** (cosine **0.9950**). A second session could not
search the first session's library. The test library was cleared afterward.
Five hosted-adapter tests cover isolation, targeted deletion, capacity, empty
uploads and empty-library search. This is a demo, not a general quality claim.

The hosted React app retains FastAPI uploads, library/job polling, search
preparation, thumbnails, range streaming and deletion. React dispatches opaque,
single-use capabilities through `@gradio/client`, preserving visitor ZeroGPU
quota headers. Four registry tests cover reuse denial, capacity, foreign
cancellation and expiry; a full-stack adapter test covers owned dispatch and
search. The combined local suites pass **40 tests**.

Local real-model React checks passed: upload/indexing, text/image/2× clip
retrieval, real video playback, foreign media denial, deletion and four widths
(320–1440 px). This supersedes the former widget demo, retained in
`hf_space/app.py` as a rollback option.
The same workflow passed against the public hosted React app using the
authorized free HF account. Real GPU indexing/search additionally passed inside
the official HF iframe, retaining a secure, partitioned browser session. The
final deployed bundle verifies exactly one session bootstrap. Anonymous run
limits were reached during QA and are not represented as unlimited usage.

Libraries are limited to three 60-second/40 MB videos and a 2 GB working-storage
threshold. Finished/failed videos expire after an hour (checked every five
minutes), or are lost on restart. Media routes retain signed-session ownership;
public Gradio file uploads/downloads and run history are disabled in the hosted
profile. Unused capabilities expire after three minutes and release capacity.
Use non-sensitive media: browser sessions are not account login. See
[the hosted profile](../hf_space/README.md) for reproduction and limitations.

Python/native tests, the React build, the full container build and non-root
startup checks pass in [GitHub Actions](https://github.com/ThanhMinh12/SceneSeek/actions/runs/38979950518).
The image serves both API and frontend, runs as UID 10001, and creates a private
session-secret file. Real model retrieval is separately verified by the native
regression above; the container startup test is not an inference benchmark.
Docker Desktop remains unavailable locally.

## Reproduce

### Branded welcome — October 18, 2026

The front page uses a custom SVG video/search mark, matching favicon, and the
headline “Less scrubbing. More finding.” beside one upload card. After upload,
the headline gives way to preparation and search; optional modes and the library
remain on demand. No external fonts, trackers, or frontend dependencies were added.
Controlled browser regressions cover the logo, five widths (320–1440 px),
the visible upload action, and existing text/image/clip/player workflows.
These are UI fixture tests, not a new model-inference or accuracy evaluation.

### Interface update — October 18, 2026

The opening screen has one main action: choose a video. Processing replaces
upload; text search appears only after a video is ready. Alternative image/clip
queries are available through the search-type selector instead of showing
three competing input panels. The Videos button opens library management only
when requested, including adding/removing videos. Limits and technical links
are available in Help; the short retention/privacy notice remains visible.
The player supports Escape, focus restoration, and keyboard focus containment.
Upload limits come from the API.

The separate `scripts/smoke_ui.py` browser suite uses explicitly controlled API
fixtures, not CLIP inference. It verifies upload validation and progress, all
three search modes, a genuinely playable in-memory video, keyboard playback
controls, empty/error results, deletion, a single runtime bootstrap, and layouts
at 320, 390, 768, and 1440 pixels. It additionally asserts one visible main
action on first load, processing replacing upload, and library management hidden
until requested. GitHub Actions runs it against the production
web build and retains screenshots. Earlier real-model results remain separate;
this update does not claim a new retrieval quality or performance benchmark.

```bash
# Build frontend/ and serve it with Vite preview first.
python scripts/smoke_ui.py --url http://127.0.0.1:4176
```

### Full pipeline

Build the C++ core, install `backend/requirements.lock` with frozen `--no-deps`
installation, install `backend/requirements-dev.txt` for tests, and run pytest.
The real regression script additionally needs httpx and optional Playwright.
Its docstring lists the real video/image/clip fixtures and expected timestamps;
the model is never substituted with deterministic predictions in that script.
