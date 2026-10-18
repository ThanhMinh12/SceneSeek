#include "sceneseek/engine_c.h"
#include "sceneseek/engine.hpp"

#include <cstring>
#include <stdexcept>

namespace {
thread_local std::string error_message;
template <typename Function, typename Result>
Result guarded(Function function, Result failure) noexcept {
  error_message.clear();
  try { return function(); }
  catch (const std::exception& error) { error_message = error.what(); }
  catch (...) { error_message = "Unknown native engine error"; }
  return failure;
}
sceneseek::Engine& engine(void* handle) {
  if (!handle) throw std::invalid_argument("Native engine handle is null");
  return *static_cast<sceneseek::Engine*>(handle);
}
std::string text(const char* value) {
  if (!value) throw std::invalid_argument("Native string argument is null");
  return value;
}
std::vector<sceneseek::Video> videos(const ss_video* values, std::size_t count) {
  if (count > 10000 || (count && !values)) throw std::invalid_argument("Invalid native video list");
  std::vector<sceneseek::Video> result;
  for (std::size_t i = 0; i < count; ++i) result.push_back({text(values[i].id), values[i].duration_seconds});
  return result;
}
std::int64_t copy_matches(const std::vector<sceneseek::Match>& matches, ss_match* output, std::size_t capacity) {
  if (matches.size() > capacity || (!matches.empty() && !output)) throw std::invalid_argument("Native result buffer is too small");
  for (std::size_t i = 0; i < matches.size(); ++i) {
    const auto& match = matches[i];
    output[i] = {match.video_index, match.frame, match.timestamp_seconds, match.end_seconds, match.score, match.playback_rate, {}};
    std::memcpy(output[i].thumbnail, match.thumbnail.c_str(), match.thumbnail.size());
  }
  return static_cast<std::int64_t>(matches.size());
}
}
extern "C" std::uint32_t ss_engine_abi_version() { return 1; }
extern "C" const char* ss_engine_last_error() { return error_message.c_str(); }
extern "C" void* ss_engine_create(const char* directory, std::uint64_t cache_bytes, std::size_t workers) {
  return guarded([&]() -> void* { return new sceneseek::Engine(text(directory), cache_bytes, workers); }, static_cast<void*>(nullptr));
}
extern "C" void ss_engine_destroy(void* handle) { delete static_cast<sceneseek::Engine*>(handle); }
extern "C" int ss_engine_save(void* handle, const char* id, const char* model, const float* embeddings,
    std::size_t rows, std::size_t dimensions, const double* timestamps, const char* const* thumbnails) {
  return guarded([&] {
    if (!embeddings || !timestamps || !thumbnails || rows == 0 || rows > 1000000 || dimensions == 0 || dimensions > 16384)
      throw std::invalid_argument("Invalid native ingestion buffers");
    std::vector<std::string> names;
    names.reserve(rows);
    for (std::size_t i = 0; i < rows; ++i) names.push_back(text(thumbnails[i]));
    engine(handle).save(text(id), text(model), {embeddings, rows * dimensions}, rows, dimensions, {timestamps, rows}, names);
    return 0;
  }, -1);
}
extern "C" int ss_engine_remove(void* handle, const char* id) {
  return guarded([&] { engine(handle).remove(text(id)); return 0; }, -1);
}
extern "C" int ss_engine_get_stats(void* handle, ss_engine_stats* output) {
  return guarded([&] {
    if (!output) throw std::invalid_argument("Native stats buffer is null");
    const auto stats = engine(handle).stats();
    *output = {stats.cached_bytes, stats.cache_limit, stats.cached_shards, stats.cache_hits, stats.cache_misses, stats.skipped_shards};
    return 0;
  }, -1);
}
extern "C" std::int64_t ss_engine_search_frames(void* handle, const float* query, std::size_t dimensions,
    const char* model, const ss_video* input, std::size_t count, std::size_t top_k, ss_match* output, std::size_t capacity) {
  return guarded([&] {
    if (!query || dimensions == 0 || dimensions > 16384) throw std::invalid_argument("Invalid query buffer");
    const auto allowed = videos(input, count);
    return copy_matches(engine(handle).search_frames({query, dimensions}, text(model), allowed, top_k), output, capacity);
  }, std::int64_t{-1});
}
extern "C" std::int64_t ss_engine_search_sequence(void* handle, const float* query, std::size_t rows,
    std::size_t dimensions, const double* timestamps, double duration, const char* model,
    const ss_video* input, std::size_t count, std::size_t top_k, ss_match* output, std::size_t capacity) {
  return guarded([&] {
    if (!query || rows == 0 || rows > 1000000 || dimensions == 0 || dimensions > 16384 || rows > 16 * 1024 * 1024 / dimensions)
      throw std::invalid_argument("Invalid sequence query buffer");
    const auto allowed = videos(input, count);
    const std::span<const double> times = timestamps ? std::span<const double>(timestamps, rows) : std::span<const double>{};
    return copy_matches(engine(handle).search_sequence({query, rows * dimensions}, rows, dimensions, times, duration, text(model), allowed, top_k), output, capacity);
  }, std::int64_t{-1});
}
