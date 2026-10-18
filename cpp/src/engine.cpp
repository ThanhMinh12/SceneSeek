#include "sceneseek/engine.hpp"

#include <algorithm>
#include <array>
#include <atomic>
#include <bit>
#include <chrono>
#include <cmath>
#include <cstring>
#include <fstream>
#include <limits>
#include <list>
#include <mutex>
#include <numeric>
#include <queue>
#include <stdexcept>
#include <thread>
#include <unordered_map>

#if defined(__unix__) || defined(__APPLE__)
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#endif

namespace sceneseek {
namespace {

constexpr std::size_t header_size = 64;
constexpr std::size_t max_rows = 1'000'000;
constexpr std::size_t max_dimensions = 16384;
constexpr std::uint64_t max_file_bytes = 8ULL * 1024 * 1024 * 1024;
constexpr std::size_t max_query_values = 16 * 1024 * 1024;
constexpr std::array<char, 8> magic{'S', 'S', 'I', 'D', 'X', '0', '0', '1'};
static_assert(sizeof(float) == 4 && std::numeric_limits<float>::is_iec559);
static_assert(sizeof(double) == 8 && std::numeric_limits<double>::is_iec559);

void require(bool condition, const char* message) {
  if (!condition) throw std::invalid_argument(message);
}

void valid_id(const std::string& id) {
  require(!id.empty() && id.size() <= 128, "Invalid video id");
  for (const unsigned char ch : id) {
    require((ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z') ||
            (ch >= '0' && ch <= '9') || ch == '-' || ch == '_', "Invalid video id");
  }
}

void valid_model(const std::string& model) {
  require(!model.empty() && model.size() <= 4096 && model.find('\0') == std::string::npos,
          "Invalid model identity");
}

void valid_thumbnail(const std::string& name) {
  require(!name.empty() && name.size() < 192 && name != "." && name != "..",
          "Invalid thumbnail name");
  for (const unsigned char ch : name) {
    require((ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z') ||
            (ch >= '0' && ch <= '9') || ch == '.' || ch == '-' || ch == '_',
            "Invalid thumbnail name");
  }
}

void valid_shape(std::size_t rows, std::size_t dimensions, std::size_t values) {
  require(rows > 0 && rows <= max_rows && dimensions > 0 && dimensions <= max_dimensions,
          "Index shape exceeds supported limits");
  require(rows <= std::numeric_limits<std::size_t>::max() / dimensions &&
          rows * dimensions == values, "Embedding shape mismatch");
}

void valid_times(std::span<const double> values) {
  double previous = -1;
  for (const auto value : values) {
    require(std::isfinite(value) && value >= 0 && value > previous,
            "Timestamps must be finite, nonnegative, and strictly increasing");
    previous = value;
  }
}

std::uint64_t hash_bytes(const unsigned char* data, std::size_t size,
                         std::uint64_t hash = 14695981039346656037ULL) {
  for (std::size_t i = 0; i < size; ++i) {
    hash ^= data[i];
    hash *= 1099511628211ULL;
  }
  return hash;
}

void append_integer(std::vector<unsigned char>& output, std::uint64_t value, unsigned bytes) {
  for (unsigned i = 0; i < bytes; ++i) output.push_back(static_cast<unsigned char>(value >> (i * 8)));
}

std::uint64_t read_integer(const unsigned char* data, std::size_t size,
                           std::size_t& offset, unsigned bytes) {
  if (offset > size || bytes > size - offset) throw std::runtime_error("Truncated index metadata");
  std::uint64_t value = 0;
  for (unsigned i = 0; i < bytes; ++i) value |= static_cast<std::uint64_t>(data[offset++]) << (i * 8);
  return value;
}

void normalize(std::span<const float> input, std::span<float> output) {
  double squared = 0;
  for (const float value : input) {
    require(std::isfinite(value), "Embeddings must contain only finite values");
    squared += static_cast<double>(value) * value;
  }
  const double denominator = squared > 0 ? std::sqrt(squared) : 1;
  for (std::size_t i = 0; i < input.size(); ++i) output[i] = static_cast<float>(input[i] / denominator);
}

float dot(std::span<const float> left, const float* right) {
  double score = 0;
  for (std::size_t i = 0; i < left.size(); ++i) score += static_cast<double>(left[i]) * right[i];
  return static_cast<float>(std::clamp(score, -1.0, 1.0));
}

class MappedFile {
 public:
  explicit MappedFile(const std::filesystem::path& path) {
#if defined(__unix__) || defined(__APPLE__)
    const int fd = open(path.c_str(), O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0) throw std::runtime_error("Cannot open native index");
    struct stat info {};
    if (fstat(fd, &info) != 0 || !S_ISREG(info.st_mode) || info.st_size < 64 ||
        static_cast<std::uint64_t>(info.st_size) > max_file_bytes ||
        static_cast<std::uint64_t>(info.st_size) > std::numeric_limits<std::size_t>::max()) {
      close(fd);
      throw std::runtime_error("Invalid native index file size or type");
    }
    size_ = static_cast<std::size_t>(info.st_size);
    void* address = mmap(nullptr, size_, PROT_READ, MAP_PRIVATE, fd, 0);
    close(fd);
    if (address == MAP_FAILED) throw std::runtime_error("Cannot memory-map native index");
    data_ = static_cast<const unsigned char*>(address);
#else
    std::ifstream input(path, std::ios::binary | std::ios::ate);
    if (!input || input.tellg() < 64 || static_cast<std::uint64_t>(input.tellg()) > max_file_bytes)
      throw std::runtime_error("Invalid native index file");
    buffer_.resize(static_cast<std::size_t>(input.tellg()));
    input.seekg(0);
    input.read(reinterpret_cast<char*>(buffer_.data()), static_cast<std::streamsize>(buffer_.size()));
    if (!input) throw std::runtime_error("Cannot read native index");
    size_ = buffer_.size();
    data_ = buffer_.data();
#endif
  }
  ~MappedFile() {
#if defined(__unix__) || defined(__APPLE__)
    if (data_) munmap(const_cast<unsigned char*>(data_), size_);
#endif
  }
  MappedFile(const MappedFile&) = delete;
  MappedFile& operator=(const MappedFile&) = delete;
  const unsigned char* data() const { return data_; }
  std::size_t size() const { return size_; }
 private:
  const unsigned char* data_ = nullptr;
  std::size_t size_ = 0;
#if !defined(__unix__) && !defined(__APPLE__)
  std::vector<unsigned char> buffer_;
#endif
};

struct Shard {
  MappedFile file;
  std::string model;
  std::size_t rows = 0;
  std::size_t dimensions = 0;
  std::vector<double> timestamps;
  std::vector<std::string> thumbnails;
  const float* vectors = nullptr;
  std::uint64_t cost = 0;

  explicit Shard(const std::filesystem::path& path) : file(path) {
    if (std::endian::native != std::endian::little) throw std::runtime_error("Native indexes require little-endian float32");
    const auto* data = file.data();
    if (std::memcmp(data, magic.data(), magic.size()) != 0) throw std::runtime_error("Unknown native index magic");
    std::size_t offset = 8;
    const auto version = read_integer(data, file.size(), offset, 4);
    dimensions = static_cast<std::size_t>(read_integer(data, file.size(), offset, 4));
    rows = static_cast<std::size_t>(read_integer(data, file.size(), offset, 8));
    const auto model_size = read_integer(data, file.size(), offset, 4);
    const auto flags = read_integer(data, file.size(), offset, 4);
    const auto metadata_size = read_integer(data, file.size(), offset, 8);
    const auto vector_offset = read_integer(data, file.size(), offset, 8);
    const auto total_size = read_integer(data, file.size(), offset, 8);
    const auto checksum = read_integer(data, file.size(), offset, 8);
    if (version != 1 || flags != 1 || dimensions == 0 || dimensions > max_dimensions ||
        rows == 0 || rows > max_rows || model_size == 0 || model_size > 4096 ||
        metadata_size > file.size() - header_size || model_size > metadata_size ||
        rows > (metadata_size - model_size) / 13 || vector_offset % 64 != 0 ||
        vector_offset < header_size + metadata_size || vector_offset > file.size() ||
        total_size != file.size() ||
        static_cast<std::uint64_t>(rows) * dimensions * 4 != total_size - vector_offset ||
        checksum != hash_bytes(data + header_size, file.size() - header_size))
      throw std::runtime_error("Corrupt or unsupported native index");
    const auto metadata_end = static_cast<std::size_t>(header_size + metadata_size);
    offset = header_size;
    model.assign(reinterpret_cast<const char*>(data + offset), static_cast<std::size_t>(model_size));
    offset += static_cast<std::size_t>(model_size);
    valid_model(model);
    timestamps.reserve(rows);
    thumbnails.reserve(rows);
    for (std::size_t row = 0; row < rows; ++row) {
      timestamps.push_back(std::bit_cast<double>(read_integer(data, metadata_end, offset, 8)));
      const auto length = read_integer(data, metadata_end, offset, 4);
      if (length == 0 || length >= 192 || length > metadata_end - offset)
        throw std::runtime_error("Corrupt native thumbnail metadata");
      thumbnails.emplace_back(reinterpret_cast<const char*>(data + offset), static_cast<std::size_t>(length));
      valid_thumbnail(thumbnails.back());
      offset += static_cast<std::size_t>(length);
    }
    if (offset != metadata_end) throw std::runtime_error("Unexpected native metadata trailing bytes");
    valid_times(timestamps);
    vectors = reinterpret_cast<const float*>(data + vector_offset);
    // Check before any optimized numeric path; malicious/corrupt NaNs never
    // reach ordering comparators or float-to-integer conversions.
    for (std::size_t i = 0; i < rows * dimensions; ++i)
      if (!std::isfinite(vectors[i])) throw std::runtime_error("Nonfinite native index vector");
    cost = file.size() + static_cast<std::uint64_t>(rows) * (sizeof(double) + sizeof(std::string)) + metadata_size;
  }
};

struct TempFile {
  std::filesystem::path path;
  ~TempFile() { std::error_code error; std::filesystem::remove(path, error); }
};

std::atomic<std::uint64_t> temporary_id{0};

template <typename Function>
void parallel_shards(std::size_t size, std::size_t workers, Function function) {
  if (size == 0) return;
  std::atomic<std::size_t> next{0};
  std::exception_ptr error;
  std::mutex error_mutex;
  auto run = [&] {
    for (;;) {
      const auto i = next.fetch_add(1);
      if (i >= size) break;
      try { function(i); }
      catch (...) { std::lock_guard lock(error_mutex); if (!error) error = std::current_exception(); }
    }
  };
  std::vector<std::jthread> threads;
  for (std::size_t i = 1; i < std::min(size, workers); ++i) threads.emplace_back(run);
  run();
  threads.clear();  // jthread joins before inspecting the shared exception.
  if (error) std::rethrow_exception(error);
}

void valid_search(const std::string& model, std::span<const Video> videos, std::size_t top_k) {
  valid_model(model);
  require(top_k > 0 && top_k <= 50 && videos.size() <= 10000, "Search size exceeds supported limits");
  std::vector<std::string> ids;
  for (const auto& video : videos) {
    valid_id(video.id);
    require(std::isfinite(video.duration_seconds) && video.duration_seconds >= 0, "Invalid video duration");
    ids.push_back(video.id);
  }
  std::sort(ids.begin(), ids.end());
  require(std::adjacent_find(ids.begin(), ids.end()) == ids.end(), "Duplicate video id in search allowlist");
}

bool better(const Match& a, const Match& b, std::span<const Video> videos) {
  if (a.score != b.score) return a.score > b.score;
  if (videos[a.video_index].id != videos[b.video_index].id)
    return videos[a.video_index].id < videos[b.video_index].id;
  if (a.timestamp_seconds != b.timestamp_seconds) return a.timestamp_seconds < b.timestamp_seconds;
  return a.frame < b.frame;
}

}  // namespace

struct Engine::Impl {
  struct Entry { std::shared_ptr<Shard> shard; std::list<std::string>::iterator position; };
  std::filesystem::path directory;
  std::uint64_t budget;
  std::size_t workers;
  mutable std::mutex cache_mutex;
  std::mutex write_mutex;
  std::list<std::string> lru;
  std::unordered_map<std::string, Entry> cache;
  std::uint64_t bytes = 0, hits = 0, misses = 0;
  std::atomic<std::uint64_t> skipped{0};

  Impl(std::filesystem::path root, std::uint64_t limit, std::size_t count)
      : directory(std::filesystem::absolute(std::move(root))), budget(limit), workers(count) {
    require(workers > 0 && workers <= 8, "Native worker count must be between 1 and 8");
    require(budget <= 4ULL * 1024 * 1024 * 1024, "Native cache budget exceeds 4 GiB");
    std::filesystem::create_directories(directory);
  }

  std::filesystem::path path(const std::string& id) const { valid_id(id); return directory / (id + ".ssidx"); }
  void evict(const std::string& id) {
    auto entry = cache.find(id);
    if (entry == cache.end()) return;
    bytes -= entry->second.shard->cost;
    lru.erase(entry->second.position);
    cache.erase(entry);
  }
  std::shared_ptr<Shard> load(const std::string& id) {
    std::lock_guard lock(cache_mutex);
    auto entry = cache.find(id);
    if (entry != cache.end()) {
      ++hits;
      lru.splice(lru.begin(), lru, entry->second.position);
      return entry->second.shard;
    }
    ++misses;
    std::shared_ptr<Shard> shard;
    try { shard = std::make_shared<Shard>(path(id)); }
    catch (const std::invalid_argument& error) { throw std::runtime_error(error.what()); }
    if (shard->cost <= budget) {
      while (bytes > budget - shard->cost && !lru.empty()) evict(lru.back());
      lru.push_front(id);
      cache.emplace(id, Entry{shard, lru.begin()});
      bytes += shard->cost;
    }
    return shard;
  }
};

Engine::Engine(std::filesystem::path directory, std::uint64_t cache_bytes, std::size_t workers)
    : impl_(std::make_unique<Impl>(std::move(directory), cache_bytes, workers)) {}
Engine::~Engine() = default;

void Engine::save(const std::string& id, const std::string& model,
                  std::span<const float> embeddings, std::size_t rows,
                  std::size_t dimensions, std::span<const double> timestamps,
                  std::span<const std::string> thumbnails) {
  valid_id(id); valid_model(model); valid_shape(rows, dimensions, embeddings.size());
  require(timestamps.size() == rows && thumbnails.size() == rows, "Index metadata length mismatch");
  valid_times(timestamps);
  require(std::endian::native == std::endian::little, "Native indexes require little-endian float32");
  std::vector<unsigned char> metadata(model.begin(), model.end());
  for (std::size_t i = 0; i < rows; ++i) {
    valid_thumbnail(thumbnails[i]);
    append_integer(metadata, std::bit_cast<std::uint64_t>(timestamps[i]), 8);
    append_integer(metadata, thumbnails[i].size(), 4);
    metadata.insert(metadata.end(), thumbnails[i].begin(), thumbnails[i].end());
  }
  const auto metadata_size = metadata.size();
  const std::uint64_t vector_offset = (header_size + metadata.size() + 63ULL) / 64 * 64;
  const std::uint64_t total = vector_offset + static_cast<std::uint64_t>(rows) * dimensions * 4;
  require(total <= max_file_bytes, "Native index exceeds file size limit");
  metadata.resize(static_cast<std::size_t>(vector_offset) - header_size, 0);
  std::lock_guard write_lock(impl_->write_mutex);
  TempFile temporary{impl_->directory / (id + ".ssidx.tmp-" +
      std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()) + "-" +
      std::to_string(temporary_id.fetch_add(1)))};
#if defined(__unix__) || defined(__APPLE__)
  const int fd = open(temporary.path.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
  if (fd < 0) throw std::runtime_error("Cannot create private temporary index");
  close(fd);
#endif
  std::ofstream output(temporary.path, std::ios::binary | std::ios::trunc);
  output.exceptions(std::ios::badbit | std::ios::failbit);
  const std::array<char, header_size> blank{};
  output.write(blank.data(), blank.size());
  output.write(reinterpret_cast<const char*>(metadata.data()), static_cast<std::streamsize>(metadata.size()));
  auto checksum = hash_bytes(metadata.data(), metadata.size());
  std::vector<float> normalized(dimensions);
  for (std::size_t row = 0; row < rows; ++row) {
    normalize(embeddings.subspan(row * dimensions, dimensions), normalized);
    const auto* data = reinterpret_cast<const unsigned char*>(normalized.data());
    checksum = hash_bytes(data, dimensions * sizeof(float), checksum);
    output.write(reinterpret_cast<const char*>(data), static_cast<std::streamsize>(dimensions * sizeof(float)));
  }
  std::vector<unsigned char> header(magic.begin(), magic.end());
  append_integer(header, 1, 4); append_integer(header, dimensions, 4);
  append_integer(header, rows, 8); append_integer(header, model.size(), 4);
  append_integer(header, 1, 4); append_integer(header, metadata_size, 8);
  append_integer(header, vector_offset, 8); append_integer(header, total, 8);
  append_integer(header, checksum, 8);
  output.seekp(0);
  output.write(reinterpret_cast<const char*>(header.data()), header.size());
  output.close();
#if defined(__unix__) || defined(__APPLE__)
  const int sync_fd = open(temporary.path.c_str(), O_RDONLY | O_CLOEXEC);
  if (sync_fd < 0) throw std::runtime_error("Cannot flush native index");
  const int sync_result = fsync(sync_fd);
  close(sync_fd);
  if (sync_result != 0) throw std::runtime_error("Cannot flush native index");
#endif
  std::lock_guard cache_lock(impl_->cache_mutex);
  std::filesystem::rename(temporary.path, impl_->path(id));
  impl_->evict(id);
#if defined(__unix__) || defined(__APPLE__)
  const int directory_fd = open(impl_->directory.c_str(), O_RDONLY | O_DIRECTORY | O_CLOEXEC);
  if (directory_fd < 0) throw std::runtime_error("Cannot flush native index directory");
  const int directory_sync = fsync(directory_fd);
  close(directory_fd);
  if (directory_sync != 0) throw std::runtime_error("Cannot flush native index directory");
#endif
}

void Engine::remove(const std::string& id) {
  valid_id(id);
  std::lock_guard write_lock(impl_->write_mutex);
  std::lock_guard cache_lock(impl_->cache_mutex);
  std::filesystem::remove(impl_->path(id));
  impl_->evict(id);
}

IndexInfo Engine::inspect(const std::string& id) {
  const auto shard = impl_->load(id);
  return {shard->rows, shard->dimensions, shard->file.size(), shard->model};
}

EngineStats Engine::stats() const {
  std::lock_guard lock(impl_->cache_mutex);
  return {impl_->bytes, impl_->budget, impl_->cache.size(), impl_->hits, impl_->misses, impl_->skipped.load()};
}

std::vector<Match> Engine::search_frames(std::span<const float> query,
    const std::string& model, std::span<const Video> videos, std::size_t top_k) {
  valid_search(model, videos, top_k);
  require(!query.empty() && query.size() <= max_dimensions, "Invalid query dimensions");
  std::vector<float> normalized(query.size());
  normalize(query, normalized);
  std::vector<std::vector<Match>> shards(videos.size());
  parallel_shards(videos.size(), impl_->workers, [&](std::size_t i) {
    std::shared_ptr<Shard> shard;
    try { shard = impl_->load(videos[i].id); }
    catch (const std::runtime_error&) { ++impl_->skipped; return; }
    if (shard->model != model || shard->dimensions != query.size()) return;
    using Candidate = std::pair<float, std::size_t>;
    const auto preferred = [](const Candidate& a, const Candidate& b) {
      return a.first != b.first ? a.first > b.first : a.second < b.second;
    };
    std::priority_queue<Candidate, std::vector<Candidate>, decltype(preferred)> heap(preferred);
    const auto limit = std::min(shard->rows, top_k * 16);
    for (std::size_t row = 0; row < shard->rows; ++row) {
      const Candidate candidate{dot(normalized, shard->vectors + row * shard->dimensions), row};
      if (heap.size() < limit) heap.push(candidate);
      else if (preferred(candidate, heap.top())) { heap.pop(); heap.push(candidate); }
    }
    std::vector<Candidate> candidates;
    while (!heap.empty()) { candidates.push_back(heap.top()); heap.pop(); }
    std::sort(candidates.begin(), candidates.end(), preferred);
    for (const auto& [score, row] : candidates) {
      const double timestamp = shard->timestamps[row];
      if (std::any_of(shards[i].begin(), shards[i].end(), [&](const auto& match) {
        return std::abs(match.timestamp_seconds - timestamp) < 3.0;
      })) continue;
      const double duration = videos[i].duration_seconds > 0 ? videos[i].duration_seconds : timestamp + 4;
      shards[i].push_back({i, row, timestamp, std::min(timestamp + 4, duration), score, 1, shard->thumbnails[row]});
      if (shards[i].size() == top_k) break;
    }
  });
  std::vector<Match> matches;
  for (auto& shard : shards) matches.insert(matches.end(), std::make_move_iterator(shard.begin()), std::make_move_iterator(shard.end()));
  std::sort(matches.begin(), matches.end(), [&](const auto& a, const auto& b) { return better(a, b, videos); });
  if (matches.size() > top_k) matches.resize(top_k);
  return matches;
}

std::vector<Match> Engine::search_sequence(std::span<const float> query,
    std::size_t query_rows, std::size_t dimensions,
    std::span<const double> query_timestamps, double query_duration,
    const std::string& model, std::span<const Video> videos, std::size_t top_k) {
  valid_search(model, videos, top_k);
  valid_shape(query_rows, dimensions, query.size());
  require(query.size() <= max_query_values, "Reference clip exceeds native workspace limit");
  require(query_timestamps.empty() || query_timestamps.size() == query_rows, "Query timestamp length mismatch");
  valid_times(query_timestamps);
  require(std::isfinite(query_duration) && query_duration >= 0 && query_duration <= 86400, "Invalid query duration");
  for (const float value : query) require(std::isfinite(value), "Query embeddings must be finite");
  std::vector<std::vector<Match>> shards(videos.size());
  parallel_shards(videos.size(), impl_->workers, [&](std::size_t i) {
    std::shared_ptr<Shard> shard;
    try { shard = impl_->load(videos[i].id); }
    catch (const std::runtime_error&) { ++impl_->skipped; return; }
    if (shard->model != model || shard->dimensions != dimensions || shard->rows < 2) return;
    std::vector<double> differences;
    for (std::size_t j = 1; j < shard->rows; ++j) differences.push_back(shard->timestamps[j] - shard->timestamps[j-1]);
    std::sort(differences.begin(), differences.end());
    const std::size_t middle = differences.size() / 2;
    const double interval = differences.size() % 2 ? differences[middle] : (differences[middle-1] + differences[middle]) / 2;
    const double duration = query_duration > 0 ? query_duration : static_cast<double>(query_rows) * interval;
    std::vector<double> times;
    if (query_timestamps.empty()) {
      for (std::size_t j = 0; j < query_rows; ++j) times.push_back(static_cast<double>(j) * interval);
    } else times.assign(query_timestamps.begin(), query_timestamps.end());
    float best_score = -std::numeric_limits<float>::infinity();
    Match best{};
    for (const double rate : {1.0, 0.5, 0.75, 1.25, 1.5, 2.0}) {
      const double step = interval / rate;
      const double stop = duration - std::min(0.1, step * 0.1);
      const double sample_count = std::ceil(stop / step);
      if (!std::isfinite(sample_count) || sample_count < 3 || sample_count > static_cast<double>(max_query_values / dimensions)) continue;
      const auto samples = static_cast<std::size_t>(sample_count);
      const double latest_start = videos[i].duration_seconds - duration * rate;
      const auto valid_starts = static_cast<std::size_t>(std::upper_bound(shard->timestamps.begin(), shard->timestamps.end(), latest_start + 1e-5) - shard->timestamps.begin());
      if (valid_starts == 0 || samples > shard->rows) continue;
      std::vector<float> resampled(samples * dimensions), raw(dimensions);
      std::size_t left = 0;
      for (std::size_t sample = 0; sample < samples; ++sample) {
        const double time = static_cast<double>(sample) * step;
        while (left + 1 < times.size() && times[left + 1] <= time) ++left;
        const auto right = std::min(left + 1, times.size() - 1);
        const double weight = time <= times.front() || left == right ? 0 : std::clamp((time - times[left]) / (times[right] - times[left]), 0.0, 1.0);
        for (std::size_t dimension = 0; dimension < dimensions; ++dimension) {
          const double first = query[left * dimensions + dimension];
          raw[dimension] = static_cast<float>(first + weight * (static_cast<double>(query[right * dimensions + dimension]) - first));
        }
        normalize(raw, std::span<float>(resampled).subspan(sample * dimensions, dimensions));
      }
      float rate_score = -std::numeric_limits<float>::infinity();
      std::size_t rate_start = 0;
      std::vector<float> scores(samples);
      const auto starts = std::min(valid_starts, shard->rows - samples + 1);
      const auto dropped = samples / 4;
      for (std::size_t start = 0; start < starts; ++start) {
        for (std::size_t sample = 0; sample < samples; ++sample)
          scores[sample] = dot(std::span<const float>(resampled).subspan(sample * dimensions, dimensions), shard->vectors + (start + sample) * dimensions);
        auto kept = scores.begin() + static_cast<std::ptrdiff_t>(dropped);
        if (dropped) std::nth_element(scores.begin(), kept, scores.end());
        const auto score = static_cast<float>(std::accumulate(kept, scores.end(), 0.0) / static_cast<double>(samples - dropped));
        if (score > rate_score) { rate_score = score; rate_start = start; }
      }
      if (rate_score > best_score + 1e-6F) {
        best_score = rate_score;
        const double timestamp = shard->timestamps[rate_start];
        best = {i, rate_start, timestamp, std::min(videos[i].duration_seconds, timestamp + duration * rate),
                rate_score, static_cast<float>(rate), shard->thumbnails[rate_start]};
      }
    }
    if (std::isfinite(best_score)) shards[i].push_back(std::move(best));
  });
  std::vector<Match> matches;
  for (auto& shard : shards) for (auto& match : shard) matches.push_back(std::move(match));
  std::sort(matches.begin(), matches.end(), [&](const auto& a, const auto& b) { return better(a, b, videos); });
  if (matches.size() > top_k) matches.resize(top_k);
  return matches;
}

}  // namespace sceneseek
