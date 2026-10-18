#pragma once

#include "sceneseek/index.h"

// All pointers refer to caller-owned buffers for the duration of each call.
// The engine copies ingestion data into its own immutable index files.
// No C++ exception is permitted to cross this ABI. Errors return -1/null;
// ss_engine_last_error() is thread-local and valid until the next ABI call.
extern "C" {

struct ss_video {
  const char* id;
  double duration_seconds;
};

struct ss_match {
  std::size_t video_index;
  std::uint64_t frame;
  double timestamp_seconds;
  double end_seconds;
  float score;
  float playback_rate;
  char thumbnail[192];
};

struct ss_engine_stats {
  std::uint64_t cached_bytes;
  std::uint64_t cache_limit;
  std::uint64_t cached_shards;
  std::uint64_t cache_hits;
  std::uint64_t cache_misses;
  std::uint64_t skipped_shards;
};

SCENESEEK_EXPORT std::uint32_t ss_engine_abi_version();
SCENESEEK_EXPORT const char* ss_engine_last_error();
SCENESEEK_EXPORT void* ss_engine_create(const char* directory,
                                      std::uint64_t cache_bytes,
                                      std::size_t workers);
SCENESEEK_EXPORT void ss_engine_destroy(void* engine);
SCENESEEK_EXPORT int ss_engine_save(void* engine, const char* id,
    const char* model, const float* embeddings, std::size_t rows,
    std::size_t dimensions, const double* timestamps,
    const char* const* thumbnails);
SCENESEEK_EXPORT int ss_engine_remove(void* engine, const char* id);
SCENESEEK_EXPORT int ss_engine_get_stats(void* engine, ss_engine_stats* output);
SCENESEEK_EXPORT std::int64_t ss_engine_search_frames(void* engine,
    const float* query, std::size_t dimensions, const char* model,
    const ss_video* videos, std::size_t video_count, std::size_t top_k,
    ss_match* output, std::size_t output_capacity);
SCENESEEK_EXPORT std::int64_t ss_engine_search_sequence(void* engine,
    const float* query, std::size_t query_rows, std::size_t dimensions,
    const double* query_timestamps, double query_duration, const char* model,
    const ss_video* videos, std::size_t video_count, std::size_t top_k,
    ss_match* output, std::size_t output_capacity);

}
