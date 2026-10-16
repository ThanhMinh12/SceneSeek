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
4. The catalog atomically replaces one compressed NumPy index per video. The
   file records the embedding-model identity, vectors, timestamps, and thumbnail
   names together so those values cannot drift apart.
5. The database marks the video searchable only after the index rename succeeds.
   A crash during processing is surfaced as an interrupted job after restart.

## Frame retrieval

Text and image queries produce a single vector in the same CLIP projection
space. Ready indexes owned by the session and built by the same pinned model
revision are searched shard by shard. A bounded 32-shard LRU cache avoids repeat
decompression without duplicating the entire library. The native core calculates:

```text
score(q, x) = (q · x) / (||q|| ||x||)
```

The top `k × 16` candidates per shard are partially sorted in C++, then a diversity pass
removes near-duplicate timestamps from the same video. This keeps the result
page useful without changing the underlying score.

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

The best valid `(start, end, rate)` tuple per video is returned. End time uses the
full reference duration times the physical rate, not the last sampled index.
Rates below 1 compress the source span; rates above 1 expand it. Hypotheses are
`0.5, 0.75, 1.0, 1.25, 1.5, 2.0`.

This algorithm preserves temporal order and handles broad speed changes while
remaining inspectable. It intentionally does not use dynamic time warping, so
local edits, reordered shots, and variable speed ramps can reduce the score.

## Native boundary

`libsceneseek_core` exposes two stable C ABI functions from a C++20
implementation. Python validates shapes and owns all memory; the library only
reads contiguous arrays and writes caller-allocated result buffers. If the
shared library is absent, NumPy implementations provide the same behavior.

## Persistence

```text
data/
├── sceneseek.sqlite3       catalog + jobs
├── uploads/<uuid>.<ext>    original videos
├── indexes/<uuid>.npz      embeddings + aligned metadata
├── thumbnails/<uuid>/*.jpg
├── playback/<uuid>.webm    browser-compatible derivative
├── .session-secret        private signing key (keep persistent, do not publish)
└── tmp/                    short-lived query uploads
```

Deleting a finished video removes the original, derivative, index, and thumbnails. Query files are always
removed in a `finally` block.

## Scaling boundaries

The single-node design favors a runnable portfolio project over premature
distributed infrastructure. Practical next steps are explicit:

- move background indexing to a durable queue before adding API replicas;
- store media and indexes in S3-compatible object storage;
- use memory-mapped shards or an ANN index for millions of frames;
- add account-based identity if browser-session isolation is insufficient;
- introduce scene-boundary sampling when fixed-interval sampling becomes too
  wasteful for long static shots.

