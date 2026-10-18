#pragma once

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <memory>
#include <span>
#include <string>
#include <vector>

namespace sceneseek {

struct Video {
  std::string id;
  double duration_seconds;
};

struct Match {
  std::size_t video_index;
  std::size_t frame;
  double timestamp_seconds;
  double end_seconds;
  float score;
  float playback_rate;
  std::string thumbnail;
};

struct IndexInfo {
  std::size_t rows;
  std::size_t dimensions;
  std::uint64_t file_bytes;
  std::string model;
};

struct EngineStats {
  std::uint64_t cached_bytes;
  std::uint64_t cache_limit;
  std::uint64_t cached_shards;
  std::uint64_t cache_hits;
  std::uint64_t cache_misses;
  std::uint64_t skipped_shards;
};

// Immutable, versioned on-disk shards. Search takes an explicit authorized
// video list, never discovers/searches other visitors' files in the directory.
// A live Engine is safe for concurrent saves, removals, and searches. Writers
// replace files atomically; readers retain immutable snapshots through RAII.
class Engine {
 public:
  explicit Engine(std::filesystem::path directory,
                  std::uint64_t cache_bytes = 64ULL * 1024 * 1024,
                  std::size_t workers = 2);
  ~Engine();
  Engine(const Engine&) = delete;
  Engine& operator=(const Engine&) = delete;

  void save(const std::string& id, const std::string& model,
            std::span<const float> embeddings, std::size_t rows,
            std::size_t dimensions, std::span<const double> timestamps,
            std::span<const std::string> thumbnails);
  void remove(const std::string& id);
  IndexInfo inspect(const std::string& id);
  EngineStats stats() const;

  std::vector<Match> search_frames(std::span<const float> query,
                                 const std::string& model,
                                 std::span<const Video> videos,
                                 std::size_t top_k);
  std::vector<Match> search_sequence(std::span<const float> query,
                                   std::size_t query_rows,
                                   std::size_t dimensions,
                                   std::span<const double> query_timestamps,
                                   double query_duration,
                                   const std::string& model,
                                   std::span<const Video> videos,
                                   std::size_t top_k);

 private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};

}  // namespace sceneseek
