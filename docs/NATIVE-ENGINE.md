# C++20 retrieval engine

`cpp/src/engine.cpp` implements the production catalog; `engine_c.cpp` exports
the stable opaque-handle ABI. `backend/sceneseek/engine.py` handles buffer shape
checks and object lifetimes, not searching/ranking. The original Python catalog
is retained in `reference_catalog.py` as a test oracle and offline fallback.

## Native file format: `.ssidx`, version 1

All scalars are little-endian; floats are IEEE 754. The verified target is Linux
x86-64. POSIX reads use read-only private mappings with symlink rejection and
regular-file/size checks. A buffered read fallback exists on non-POSIX systems;
Windows replacement/packaging has not been deployment-tested.

The 64-byte header contains, in order:

| Field | Bytes |
| --- | ---: |
| `SSIDX001` magic | 8 |
| format version, embedding dimensions | 4 each |
| vector row count | 8 |
| model identity byte length, normalized-vector flag | 4 each |
| metadata bytes, vector offset, total file bytes, payload checksum | 8 each |

Metadata is the UTF-8 model identity followed by each row's timestamp (float64),
thumbnail-name length (uint32), and basename bytes. Padding aligns vectors to
64 bytes. Row-major float32 unit-normalized vectors occupy the rest of the file.
Zero vectors remain zero. FNV-1a-64 covers metadata, padding, and vectors; it is
a corruption check, **not authentication or a cryptographic signature**.

Loading validates shape arithmetic, version/flags, offsets, exact byte counts,
checksum, finite floats, strictly increasing nonnegative timestamps, and safe
thumbnail basenames. Limits: one million rows per shard, 16,384 dimensions,
8 GiB files, 191-byte basenames, and 4,096-byte model identities. IDs contain only
ASCII letters, digits, `_`, and `-` (maximum 128 bytes). Writes are streamed to
0600 temporary files on POSIX, fsynced, atomically renamed, and directory-fsynced.

## Memory and concurrency

The LRU charges mapped bytes plus an estimate of copied metadata. A shard larger
than the budget is used transiently, not retained. Active readers can hold older
snapshots after eviction/replacement. The budget is **not a process RSS cap**:
OS page residency, in-flight mappings, model memory, and reference-clip workspace
are separate. Sequence resampling is capped at 16 million float values per worker.
Search fan-out is bounded to 1–8 workers; default 2. Each shard keeps bounded top-k
candidates; complete libraries are never concatenated into a second dense matrix.

Authorization is performed in FastAPI/SQLite. Each engine query receives only
the caller's ready-video allowlist. The engine never searches directory contents
or returns private cache statistics through the public API. Missing/corrupt
shards are skipped with an internal counter; model/dimension mismatches are skipped.

## CLI

Build with CMake, then run `build/sceneseek --help`. Docker also includes
`/usr/local/bin/sceneseek`. No Python/CLIP runtime is needed for CLI operations.
Input matrices are whitespace-delimited text: `rows dimensions`, then row-major
finite float values. These are **precomputed embeddings**, not raw videos.

```bash
# A shell example, after preparing matrix.txt and query.txt externally:
build/sceneseek index /tmp/my-index video-a clip-model matrix.txt 1.0
build/sceneseek inspect /tmp/my-index video-a
build/sceneseek search /tmp/my-index clip-model query.txt video-a:60
# Reference matrix sampled every .5s, full reference duration 8s:
build/sceneseek sequence /tmp/my-index clip-model clip.txt .5 8 video-a:60
build/sceneseek benchmark 100000 512 10 4 256 2
```

Indexing generates timestamp/thumbnail metadata on the specified fixed sampling
grid. `search` takes a one-row query; `sequence` accepts multiple rows. Queries
take explicit `ID:DURATION` lists and emit JSON. Library callers can supply actual
irregular source timestamps. The CLI supports inspecting and querying existing
files, but does not migrate `.npz` archives; the Python adapter handles migration.

## Verification

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DSCENESEEK_BUILD_TESTS=ON
cmake --build build --parallel 2
ctest --test-dir build --output-on-failure
cmake -S . -B /tmp/sceneseek-asan -DCMAKE_BUILD_TYPE=Debug -DSCENESEEK_SANITIZERS=ON
cmake --build /tmp/sceneseek-asan --parallel 2
ctest --test-dir /tmp/sceneseek-asan --output-on-failure
cd backend && python -m pytest
```

Native tests cover restart persistence, validation/corruption, private file modes,
symlink rejection, cache eviction/bypass, immutable concurrent replacements,
six physical playback rates, and C ABI error buffers. Python integration tests
compare complete native results to NumPy, test owner allowlists, legacy migration,
CLI round trips, invalid buffers, and concurrent bridge calls. Genuine model
checks are separate from deterministic vectors and synthetic benchmarks.
