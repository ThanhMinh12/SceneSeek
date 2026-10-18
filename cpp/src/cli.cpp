#include "sceneseek/engine.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <random>
#include <sstream>
#include <stdexcept>
#if defined(__linux__)
#include <sys/resource.h>
#endif

namespace {
using Clock = std::chrono::steady_clock;

std::string quote(const std::string& value) {
  std::ostringstream out;
  out << '"';
  for (const unsigned char ch : value) {
    if (ch == '"' || ch == '\\') out << '\\' << ch;
    else if (ch < 32) out << "\\u" << std::hex << std::setw(4) << std::setfill('0') << static_cast<int>(ch) << std::dec;
    else out << ch;
  }
  out << '"';
  return out.str();
}

std::size_t integer(const char* value, std::size_t limit) {
  const std::string input(value);
  std::size_t consumed = 0;
  if (input.empty() || input[0] == '-') throw std::invalid_argument("Expected a positive integer");
  const auto result = std::stoull(input, &consumed);
  if (consumed != input.size() || result == 0 || result > limit) throw std::invalid_argument("Integer argument outside supported range");
  return static_cast<std::size_t>(result);
}

double number(const std::string& value) {
  std::size_t consumed = 0;
  const auto result = std::stod(value, &consumed);
  if (consumed != value.size() || !std::isfinite(result) || result <= 0) throw std::invalid_argument("Expected a finite positive number");
  return result;
}

struct Matrix { std::size_t rows, dimensions; std::vector<float> values; };
Matrix matrix(const char* path) {
  std::ifstream input(path);
  Matrix result{};
  if (!(input >> result.rows >> result.dimensions) || !result.rows || result.rows > 1000000 ||
      !result.dimensions || result.dimensions > 16384 || result.rows > 64 * 1024 * 1024 / result.dimensions)
    throw std::invalid_argument("Matrix header must be rows dimensions, within the CLI workspace limit");
  result.values.resize(result.rows * result.dimensions);
  for (auto& value : result.values) if (!(input >> value) || !std::isfinite(value)) throw std::invalid_argument("Invalid/truncated matrix values");
  std::string trailing;
  if (input >> trailing) throw std::invalid_argument("Unexpected matrix trailing values");
  return result;
}

void save(sceneseek::Engine& engine, const std::string& id, const std::string& model,
          const Matrix& values, double interval) {
  std::vector<double> timestamps;
  std::vector<std::string> thumbnails;
  for (std::size_t i = 0; i < values.rows; ++i) {
    timestamps.push_back(static_cast<double>(i) * interval);
    std::ostringstream name;
    name << std::setw(6) << std::setfill('0') << i << ".jpg";
    thumbnails.push_back(name.str());
  }
  engine.save(id, model, values.values, values.rows, values.dimensions, timestamps, thumbnails);
}

void print_matches(const std::vector<sceneseek::Match>& matches, const std::vector<sceneseek::Video>& videos) {
  std::cout << '[';
  bool comma = false;
  for (const auto& match : matches) {
    if (comma) std::cout << ',';
    comma = true;
    std::cout << "{\"video_id\":" << quote(videos[match.video_index].id)
              << ",\"timestamp_seconds\":" << match.timestamp_seconds
              << ",\"end_seconds\":" << match.end_seconds
              << ",\"score\":" << match.score << ",\"playback_rate\":" << match.playback_rate
              << ",\"thumbnail\":" << quote(match.thumbnail) << '}';
  }
  std::cout << "]\n";
}

struct BenchmarkDirectory {
  std::filesystem::path path;
  std::vector<std::string> ids;
  BenchmarkDirectory() {
    std::random_device random;
    for (int attempt = 0; attempt < 20; ++attempt) {
      path = std::filesystem::temp_directory_path() / ("sceneseek-bench-" + std::to_string(random()) + "-" + std::to_string(random()));
      if (std::filesystem::create_directory(path)) return;
    }
    throw std::runtime_error("Could not create private benchmark directory");
  }
  ~BenchmarkDirectory() {
    // Never recursively remove a directory: only exact files this benchmark created.
    std::error_code error;
    for (const auto& id : ids) std::filesystem::remove(path / (id + ".ssidx"), error);
    std::filesystem::remove(path, error);
  }
};

int benchmark(int argc, char** argv) {
  const auto rows = argc > 2 ? integer(argv[2], 1000000) : 100000;
  const auto dimensions = argc > 3 ? integer(argv[3], 4096) : 512;
  const auto repeats = argc > 4 ? integer(argv[4], 1000) : 10;
  const auto count = argc > 5 ? integer(argv[5], 100) : 4;
  const auto cache_mib = argc > 6 ? integer(argv[6], 4096) : 64;
  const auto workers = argc > 7 ? integer(argv[7], 8) : 2;
  if (rows < count || rows * dimensions > 128 * 1024 * 1024) throw std::invalid_argument("Benchmark exceeds workspace limits");
  BenchmarkDirectory directory;
  sceneseek::Engine engine(directory.path, cache_mib * 1024ULL * 1024, workers);
  std::vector<sceneseek::Video> videos;
  std::vector<float> query(dimensions, 0);
  query[0] = 1;
  std::mt19937 random(23);
  std::normal_distribution<float> distribution;
  for (std::size_t shard = 0; shard < count; ++shard) {
    const auto shard_rows = rows / count + (shard < rows % count ? 1 : 0);
    Matrix values{shard_rows, dimensions, std::vector<float>(shard_rows * dimensions)};
    for (auto& value : values.values) value = distribution(random);
    if (shard == 0) std::copy(query.begin(), query.end(), values.values.begin());
    const auto id = "video-" + std::to_string(shard);
    directory.ids.push_back(id);
    save(engine, id, "synthetic", values, 1);
    videos.push_back({id, static_cast<double>(shard_rows)});
  }
  const auto cold_start = Clock::now();
  const auto first = engine.search_frames(query, "synthetic", videos, 10);
  const double cold_ms = std::chrono::duration<double, std::milli>(Clock::now() - cold_start).count();
  if (first.empty() || first[0].video_index != 0 || first[0].frame != 0 || first[0].score < .999F)
    throw std::runtime_error("Benchmark retrieval correctness check failed");
  std::vector<double> times;
  for (std::size_t i = 0; i < repeats; ++i) {
    const auto start = Clock::now();
    const auto found = engine.search_frames(query, "synthetic", videos, 10);
    if (found.empty() || found[0].frame != 0 || found[0].video_index != 0) throw std::runtime_error("Unstable benchmark result");
    times.push_back(std::chrono::duration<double, std::milli>(Clock::now() - start).count());
  }
  std::sort(times.begin(), times.end());
  const auto stats = engine.stats();
  std::cout << "{\"synthetic_embeddings\":true,\"includes_model_inference\":false,\"rows\":" << rows
            << ",\"dimensions\":" << dimensions << ",\"shards\":" << count << ",\"workers\":" << workers << ",\"repeats\":" << repeats
            << ",\"cold_ms\":" << cold_ms << ",\"p50_ms\":" << times[(times.size()-1)/2]
            << ",\"p95_ms\":" << times[static_cast<std::size_t>(std::ceil(.95 * static_cast<double>(times.size()))) - 1]
            << ",\"cached_bytes\":" << stats.cached_bytes << ",\"cache_limit\":" << stats.cache_limit;
#if defined(__linux__)
  struct rusage usage {};
  if (getrusage(RUSAGE_SELF, &usage) == 0) std::cout << ",\"peak_rss_kib\":" << usage.ru_maxrss;
#endif
  std::cout << "}\n";
  return 0;
}

void help() {
  std::cout << "SceneSeek C++20 retrieval engine\n"
      "  sceneseek index DIR ID MODEL MATRIX.txt INTERVAL\n"
      "  sceneseek inspect DIR ID\n"
      "  sceneseek search DIR MODEL QUERY.txt ID:DURATION [ID:DURATION ...]\n"
      "  sceneseek sequence DIR MODEL QUERY.txt QUERY_INTERVAL QUERY_DURATION ID:DURATION [...]\n"
      "  sceneseek benchmark [ROWS=100000] [DIM=512] [REPEATS=10] [SHARDS=4] [CACHE_MIB=64] [WORKERS=2]\n"
      "Matrix text format: rows dimensions, followed by row-major float values.\n"
      "The CLI operates on precomputed embeddings, not raw video/model inference.\n";
}
}

int main(int argc, char** argv) {
  try {
    std::cout << std::setprecision(9);
    if (argc < 2 || std::string(argv[1]) == "--help") { help(); return 0; }
    const std::string command = argv[1];
    if (command == "benchmark") return benchmark(argc, argv);
    if (argc < 4) throw std::invalid_argument("Not enough arguments; use --help");
    sceneseek::Engine engine(argv[2]);
    if (command == "inspect" && argc == 4) {
      const auto info = engine.inspect(argv[3]);
      std::cout << "{\"rows\":" << info.rows << ",\"dimensions\":" << info.dimensions << ",\"file_bytes\":" << info.file_bytes << ",\"model\":" << quote(info.model) << "}\n";
    } else if (command == "index" && argc == 7) {
      const auto values = matrix(argv[5]);
      save(engine, argv[3], argv[4], values, number(argv[6]));
      std::cout << "{\"indexed_rows\":" << values.rows << "}\n";
    } else if (command == "search" || command == "sequence") {
      const bool sequence = command == "sequence";
      if (argc < (sequence ? 8 : 6)) throw std::invalid_argument("Missing query/video arguments");
      const auto query = matrix(argv[4]);
      std::vector<sceneseek::Video> videos;
      for (int i = sequence ? 7 : 5; i < argc; ++i) {
        const std::string value = argv[i];
        const auto colon = value.find(':');
        if (colon == std::string::npos) throw std::invalid_argument("Video arguments must be ID:DURATION");
        videos.push_back({value.substr(0, colon), number(value.substr(colon+1))});
      }
      if (sequence) {
        std::vector<double> times;
        const auto interval = number(argv[5]);
        for (std::size_t i = 0; i < query.rows; ++i) times.push_back(static_cast<double>(i) * interval);
        print_matches(engine.search_sequence(query.values, query.rows, query.dimensions, times, number(argv[6]), argv[3], videos, 10), videos);
      } else {
        if (query.rows != 1) throw std::invalid_argument("Frame search requires one query row");
        print_matches(engine.search_frames(query.values, argv[3], videos, 10), videos);
      }
    } else throw std::invalid_argument("Invalid command/arguments; use --help");
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "sceneseek: " << error.what() << '\n';
    return 1;
  }
}
