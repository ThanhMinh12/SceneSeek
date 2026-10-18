# Native retrieval measurements

These are synthetic-vector **retrieval** measurements from one local Linux
x86-64 run (GCC 13.3, CMake Release, 2 search workers, 4 shards). They are not
CLIP latency, retrieval-quality measurements, hosting guarantees, or p99 results.
Every run verifies that the injected exact-match vector ranks first.

| Rows × dimensions | Cache budget | Repeats | First search | Subsequent p50 | Subsequent p95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 20,000 × 512 | 64 MiB | 10 | 124.2 ms | 9.0 ms | 13.2 ms |
| 100,000 × 512 | 64 MiB | 5 | 591.7 ms | 595.2 ms | 650.1 ms |
| 100,000 × 512 | 256 MiB | 10 | 652.1 ms | 45.6 ms | 62.2 ms |

The 100,000-row library exceeds the 64 MiB retention budget, so repeated scans
thrash the LRU and revalidate/map cold shards. A 256 MiB budget retains the four
shards (213,200,356 charged bytes), avoiding repeat checksum/metadata work.
The larger-cache run reported peak process RSS **306,940 KiB**, which includes
fixture generation and mapped pages, not just the cache. This illustrates why
cache budget and total RSS must not be conflated.

“First search” includes file opening, checksum/metadata validation, mapping, and
scoring; OS caches were not explicitly flushed. “Subsequent” does not imply that
all shards fit in cache. Timing noise, CPU, dimensions, and data distribution
affect results. Larger cache settings are a tradeoff, not an automatic production
recommendation or a reason to provision paid hardware.

Reproduce on your own machine:

```bash
build/sceneseek benchmark 20000 512 10 4 64 2
build/sceneseek benchmark 100000 512 5 4 64 2
build/sceneseek benchmark 100000 512 10 4 256 2
```

The CLI emits JSON with the seed-controlled workload, cold/p50/p95 timings,
worker count, cache budget/retention, and Linux peak RSS. Comparison with another
implementation requires the same workload, hardware, cache state, precision,
diversity semantics, and inclusion/exclusion of I/O and model inference.
