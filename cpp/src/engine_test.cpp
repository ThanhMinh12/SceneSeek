#include "sceneseek/engine.hpp"
#include "sceneseek/engine_c.h"

#ifdef NDEBUG
#undef NDEBUG
#endif
#include <array>
#include <cassert>
#include <cmath>
#include <fstream>
#include <iostream>
#include <limits>
#include <random>
#include <thread>

namespace {
struct Directory {
  std::filesystem::path path;
  Directory() {
    std::random_device random;
    for (int attempt = 0; attempt < 20; ++attempt) {
      path = std::filesystem::temp_directory_path() / ("sceneseek-test-" + std::to_string(random()) + "-" + std::to_string(random()));
      if (std::filesystem::create_directory(path)) return;
    }
    throw std::runtime_error("Cannot create private test directory");
  }
  ~Directory() {
    std::error_code error;
    for (const auto& entry : std::filesystem::directory_iterator(path)) std::filesystem::remove(entry.path(), error);
    std::filesystem::remove(path, error);
  }
};

template <typename Function> void rejects(Function function) {
  bool rejected = false;
  try { function(); } catch (const std::exception&) { rejected = true; }
  assert(rejected);
}

void save(sceneseek::Engine& engine, const std::string& id, const std::vector<float>& matrix,
          std::size_t rows, std::size_t dimensions, const std::string& model = "test") {
  std::vector<double> times;
  std::vector<std::string> names;
  for (std::size_t i = 0; i < rows; ++i) {
    times.push_back(static_cast<double>(i) * 3);
    names.push_back(std::to_string(i) + ".jpg");
  }
  engine.save(id, model, matrix, rows, dimensions, times, names);
}

void persistence_and_scope() {
  Directory directory;
  {
    sceneseek::Engine writer(directory.path);
    save(writer, "a", {2, 0, 0, 2, -2, 0}, 3, 2);
    save(writer, "private", {100, 0}, 1, 2);
  }
  sceneseek::Engine engine(directory.path);
  const std::vector<sceneseek::Video> videos{{"a", 9}};
  const std::array<float, 2> query{1, 0};
  const auto result = engine.search_frames(query, "test", videos, 3);
  assert(result.size() == 3 && result[0].frame == 0 && result[1].frame == 1 && result[2].frame == 2);
  assert(std::abs(result[0].score - 1) < 1e-6 && result[0].thumbnail == "0.jpg");
  assert(result[0].video_index == 0 && result[1].timestamp_seconds == 3);
  assert(engine.search_frames(query, "other-model", videos, 3).empty());
  assert(engine.search_frames(query, "test", {}, 3).empty());
  const auto info = engine.inspect("a");
  assert(info.rows == 3 && info.dimensions == 2 && info.model == "test");
  engine.remove("a");
  assert(engine.search_frames(query, "test", videos, 3).empty());
  assert(std::filesystem::exists(directory.path / "private.ssidx"));
  assert(engine.stats().skipped_shards == 1);
}

void bounds_and_atomicity() {
  Directory directory;
  sceneseek::Engine engine(directory.path);
  save(engine, "a", {1, 0}, 1, 2);
  rejects([&] { save(engine, "../escape", {1, 0}, 1, 2); });
  rejects([&] { save(engine, "bad", {1, 0}, 1, 3); });
  rejects([&] { save(engine, "bad", {1, 0}, 1, 2, ""); });
  rejects([&] { save(engine, "a", {std::numeric_limits<float>::quiet_NaN(), 0}, 1, 2); });
  rejects([&] { engine.save("a", "test", std::array<float, 2>{1, 0}, 1, 2,
      std::array<double, 1>{0}, std::array<std::string, 1>{"../secret"}); });
  rejects([&] { engine.save("a", "test", std::array<float, 2>{1, 0}, 2, 1,
      std::array<double, 2>{1, 1}, std::array<std::string, 2>{"0.jpg", "1.jpg"}); });
  const std::vector<sceneseek::Video> videos{{"a", 1}};
  assert(engine.search_frames(std::array<float, 2>{1, 0}, "test", videos, 1)[0].score > .999F);
  rejects([&] { engine.search_frames(std::array<float, 2>{1, 0}, "test", videos, 0); });
  rejects([&] { engine.search_frames(std::array<float, 2>{1, 0}, "test", std::array<sceneseek::Video, 2>{{{"a", 1}, {"a", 1}}}, 1); });
  rejects([&] { engine.search_frames(std::array<float, 2>{INFINITY, 0}, "test", videos, 1); });
  for (const auto& entry : std::filesystem::directory_iterator(directory.path)) assert(entry.path().extension() == ".ssidx");
#if defined(__unix__) || defined(__APPLE__)
  const auto permissions = std::filesystem::status(directory.path / "a.ssidx").permissions();
  assert((permissions & (std::filesystem::perms::group_all | std::filesystem::perms::others_all)) == std::filesystem::perms::none);
  std::filesystem::create_symlink(directory.path / "a.ssidx", directory.path / "link.ssidx");
  rejects([&] { engine.inspect("link"); });
#endif
}

void corrupt_files() {
  Directory directory;
  {
    sceneseek::Engine engine(directory.path);
    save(engine, "a", {1, 0}, 1, 2);
    save(engine, "b", {1, 0}, 1, 2);
    save(engine, "c", {1, 0}, 1, 2);
  }
  std::filesystem::resize_file(directory.path / "a.ssidx", 10);
  {
    std::fstream file(directory.path / "b.ssidx", std::ios::binary | std::ios::in | std::ios::out);
    file.seekp(-1, std::ios::end);
    file.put('x');
  }
  {
    std::fstream file(directory.path / "c.ssidx", std::ios::binary | std::ios::in | std::ios::out);
    file.seekp(16);
    for (int i = 0; i < 8; ++i) file.put('\xff');
  }
  sceneseek::Engine engine(directory.path);
  for (const auto* id : {"a", "b", "c"}) rejects([&] { engine.inspect(id); });
  const std::vector<sceneseek::Video> videos{{"a", 1}, {"b", 1}, {"c", 1}};
  assert(engine.search_frames(std::array<float, 2>{1, 0}, "test", videos, 1).empty());
}

void bounded_cache_and_replacement() {
  Directory directory;
  sceneseek::Engine engine(directory.path, 1000);
  save(engine, "a", std::vector<float>(8 * 8, .1F), 8, 8);
  save(engine, "b", std::vector<float>(8 * 8, .2F), 8, 8);
  engine.inspect("a"); engine.inspect("b"); engine.inspect("b");
  const auto stats = engine.stats();
  assert(stats.cached_bytes <= stats.cache_limit && stats.cached_shards == 1 && stats.cache_hits == 1);
  save(engine, "b", {1, 0}, 1, 2);
  assert(engine.inspect("b").dimensions == 2);
  sceneseek::Engine bypass(directory.path, 0);
  assert(bypass.inspect("a").rows == 8 && bypass.stats().cached_bytes == 0);
}

void physical_playback_rates() {
  Directory directory;
  sceneseek::Engine engine(directory.path);
  std::vector<float> target(20 * 20, 0);
  std::vector<double> times;
  std::vector<std::string> names;
  for (std::size_t i = 0; i < 20; ++i) {
    target[i * 20 + i] = 1;
    times.push_back(static_cast<double>(i) * 2);
    names.push_back(std::to_string(i) + ".jpg");
  }
  engine.save("target", "test", target, 20, 20, times, names);
  const std::vector<sceneseek::Video> videos{{"target", 40}};
  for (const auto rate : {.5, .75, 1., 1.25, 1.5, 2.}) {
    const double duration = 12 / rate;
    const auto rows = static_cast<std::size_t>(std::ceil(duration / .1));
    std::vector<float> query(rows * 20, 0);
    std::vector<double> query_times;
    for (std::size_t i = 0; i < rows; ++i) {
      const double time = static_cast<double>(i) * .1;
      const double position = (6 + time * rate) / 2;
      const auto first = static_cast<std::size_t>(position);
      const double weight = position - static_cast<double>(first);
      query[i * 20 + first] = static_cast<float>(1 - weight);
      query[i * 20 + first + 1] = static_cast<float>(weight);
      query_times.push_back(time);
    }
    const auto result = engine.search_sequence(query, rows, 20, query_times, duration, "test", videos, 1);
    assert(result.size() == 1 && result[0].score > .999F);
    assert(result[0].timestamp_seconds == 6 && std::abs(result[0].end_seconds - 18) < 1e-5);
    assert(std::abs(result[0].playback_rate - rate) < 1e-5);
  }
}

void parallel_snapshots_and_c_abi() {
  Directory directory;
  sceneseek::Engine engine(directory.path, 4096, 4);
  save(engine, "a", {1, 0}, 1, 2);
  const std::vector<sceneseek::Video> videos{{"a", 1}};
  std::vector<std::jthread> readers;
  for (int i = 0; i < 4; ++i) readers.emplace_back([&] {
    for (int iteration = 0; iteration < 50; ++iteration) {
      const auto result = engine.search_frames(std::array<float, 2>{1, 0}, "test", videos, 1);
      assert(result.size() == 1 && std::isfinite(result[0].score));
    }
  });
  for (int i = 0; i < 30; ++i) save(engine, "a", i % 2 ? std::vector<float>{1, 0} : std::vector<float>{0, 1}, 1, 2);
  readers.clear();
  assert(ss_engine_abi_version() == 1);
  assert(ss_engine_create(nullptr, 0, 1) == nullptr);
  assert(std::string(ss_engine_last_error()).size() > 0);
  assert(ss_engine_get_stats(nullptr, nullptr) == -1);
  void* handle = ss_engine_create(directory.path.string().c_str(), 4096, 2);
  assert(handle != nullptr);
  const ss_video allowed{"a", 1};
  const float query[2] = {1, 0};
  ss_match output{};
  assert(ss_engine_search_frames(handle, query, 2, "test", &allowed, 1, 1, &output, 1) == 1);
  assert(output.video_index == 0 && output.thumbnail[0] == '0');
  assert(ss_engine_search_frames(handle, query, 2, "test", &allowed, 1, 1, nullptr, 0) == -1);
  ss_engine_destroy(handle);
}
}

int main() {
  persistence_and_scope(); bounds_and_atomicity(); corrupt_files();
  bounded_cache_and_replacement(); physical_playback_rates(); parallel_snapshots_and_c_abi();
  std::cout << "SceneSeek native engine: persistence, isolation, validation, cache, six playback rates, concurrency, ABI passed\n";
}
