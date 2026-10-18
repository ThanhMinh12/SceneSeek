# Architecture

## Indexing lifecycle

1. `POST /api/videos` streams an allowlisted video type to a UUID-named file and
   creates `videos` and `jobs` rows in SQLite.
2. A bounded single-worker executor samples frames at absolute timestamps with
   OpenCV. This avoids accumulated rounding drift at fractional frame strides.
   Every sampled frame receives a source timestamp and JPEG thumbnail. A silent
   WebM playback derivative is generated with bounded FFmpeg time/threads.
3. The lazy CLIP service loads the PyTorch model once, batches the images, and
   emits normalized `float32` vectors.
4. C++ normalizes vectors once and atomically replaces one checksummed `.ssidx`
   shard per video. Model identity, timestamps, and thumbnail names are serialized
   with the vectors. File and parent-directory fsync precede successful return.
5. The database marks the video searchable only after the index rename succeeds.
   A crash during processing is surfaced as an interrupted job after restart.

## Frame retrieval

Text and image queries produce a single vector in the same CLIP projection
space. Ready indexes owned by the session and built by the same pinned model
revision are passed explicitly to C++, which never discovers additional videos
by scanning disk. Immutable shards are memory-mapped on POSIX and retained in a
byte-budgeted LRU (default 64 MiB); oversized shards bypass retention. Two worker
threads by default search separate shards. Normalizing vectors at ingestion and
queries once reduces cosine scoring to dot products:

```text
score(q, x) = (q · x) / (||q|| ||x||)
```

C++ keeps a bounded heap of `k × 16` candidates per shard, then suppresses moments
within three seconds of a stronger result from that video. Keeping at most `k`
diverse results per video before the global merge is equivalent to the previous
global diversity pass because suppression never crosses video boundaries.
Ties resolve by score, video ID, timestamp, then frame number, independently of
worker scheduling. Python only maps returned native metadata to REST URLs.

## Sequence retrieval

An example clip is sampled more densely than the library. For each indexed video
and physical playback-rate hypothesis `r`, query features are interpolated at
reference times spaced `target_sample_interval / r`. The resulting sequence is
slid over consecutive target frames, so different sampling intervals do not
change the meaning of a playback rate:

```text
query_time[i] = i × target_sample_interval / r
aligned[i] = cosine(interpolate(query, query_time[i]), target[start + i])
score = mean(highest ceil(0.75 × number_of_samples) aligned values)
```

C++ now owns interpolation, temporal-grid construction, rate hypotheses, robust
scoring, and final result ranking. The best valid `(start, end, rate)` tuple per video is returned. End time uses the
full reference duration times the physical rate, not the last sampled index.
Rates below 1 compress the source span; rates above 1 expand it. Hypotheses are
`0.5, 0.75, 1.0, 1.25, 1.5, 2.0`.

This algorithm preserves temporal order and handles broad speed changes while
remaining inspectable. It intentionally does not use dynamic time warping, so
local edits, reordered shots, and variable speed ramps can reduce the score.

## Native boundary

`libsceneseek_core` exports an opaque engine handle through a versioned C ABI.
Exceptions become thread-local error messages/status codes, never exceptions
crossing the FFI. Python validates buffer shapes, retains NumPy arguments for
the call, and uses a finalizer to release the native engine. C++ owns persistent
shards, mapped-file lifetimes, cache state, and numeric/search work. Original
kernel functions remain ABI-compatible for regression tests and older callers.

Writes use private temporary files and atomic replacement; readers retain
shared RAII snapshots while a shard is replaced or removed. A cache mutex
coordinates mapping/eviction and a write mutex serializes native mutations.
The deployment remains single-process: cross-process mutation and external
in-place truncation of mapped files are unsupported. Missing/corrupt shards are
skipped and counted in native stats; use `sceneseek inspect` to diagnose them.

The NumPy reference path is only for unbuilt offline development and parity
tests. `SCENESEEK_REQUIRE_NATIVE=true` makes production fail at startup rather
than silently becoming Python retrieval. `/api/health` independently reports
`retrieval_engine: cpp` and `index_storage: ssidx-v1`.

## Persistence

```text
data/
├── sceneseek.sqlite3       catalog + jobs
├── uploads/<uuid>.<ext>    original videos
├── indexes/<uuid>.ssidx    native vectors + timestamps/model/thumbnail metadata
├── indexes/<uuid>.npz      optional retained legacy archive after migration
├── thumbnails/<uuid>/*.jpg
├── playback/<uuid>.webm    browser-compatible derivative
├── .session-secret        private signing key (keep persistent, do not publish)
└── tmp/                    short-lived query uploads
```

Only authorized ready-video archives migrate, under a migration/removal lock.
Original `.npz` archives remain recoverable until explicit video deletion;
both formats are removed on deletion. Any native-format library requires the
C++ engine: the adapter will not silently serve a possibly stale recovery archive.

Deleting a finished video removes the original, derivative, index, and thumbnails. Query files are always
removed in a `finally` block.

## Scaling boundaries

The single-node design favors a runnable portfolio project over premature
distributed infrastructure. Practical next steps are explicit:

- move background indexing to a durable queue before adding API replicas;
- store media and indexes in S3-compatible object storage;
- evaluate ANN indexing for workloads where exact mapped scans remain too slow;
- add account-based identity if browser-session isolation is insufficient;
- introduce scene-boundary sampling when fixed-interval sampling becomes too
  wasteful for long static shots.

