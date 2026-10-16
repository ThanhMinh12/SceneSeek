#include "sceneseek/index.h"

#include <algorithm>
#include <cmath>
#include <limits>
#include <numeric>
#include <utility>
#include <vector>

namespace {

float cosine(const float* left, const float* right, std::size_t dimensions) {
  double dot = 0.0;
  double left_norm = 0.0;
  double right_norm = 0.0;
  for (std::size_t i = 0; i < dimensions; ++i) {
    const double l = left[i];
    const double r = right[i];
    dot += l * r;
    left_norm += l * l;
    right_norm += r * r;
  }
  if (left_norm <= 0.0 || right_norm <= 0.0) {
    return 0.0F;
  }
  return static_cast<float>(dot / std::sqrt(left_norm * right_norm));
}

}  // namespace

extern "C" std::size_t ss_top_k_cosine(
    const float* query,
    const float* matrix,
    std::size_t rows,
    std::size_t dimensions,
    std::size_t k,
    std::int64_t* indices_out,
    float* scores_out) {
  if (query == nullptr || matrix == nullptr || indices_out == nullptr ||
      scores_out == nullptr || rows == 0 || dimensions == 0 || k == 0) {
    return 0;
  }

  const std::size_t result_count = std::min(rows, k);
  std::vector<std::pair<float, std::int64_t>> scored;
  scored.reserve(rows);
  for (std::size_t row = 0; row < rows; ++row) {
    scored.emplace_back(
        cosine(query, matrix + row * dimensions, dimensions),
        static_cast<std::int64_t>(row));
  }

  const auto better = [](const auto& left, const auto& right) {
    if (left.first == right.first) {
      return left.second < right.second;
    }
    return left.first > right.first;
  };
  std::partial_sort(scored.begin(), scored.begin() + result_count, scored.end(), better);

  for (std::size_t i = 0; i < result_count; ++i) {
    scores_out[i] = scored[i].first;
    indices_out[i] = scored[i].second;
  }
  return result_count;
}

extern "C" float ss_best_sequence_match(
    const float* query,
    std::size_t query_rows,
    const float* target,
    std::size_t target_rows,
    std::size_t dimensions,
    const float* playback_rates,
    std::size_t rate_count,
    std::size_t* target_start_out,
    std::size_t* target_end_out,
    float* playback_rate_out) {
  if (query == nullptr || target == nullptr || playback_rates == nullptr ||
      target_start_out == nullptr || target_end_out == nullptr ||
      playback_rate_out == nullptr || query_rows == 0 || target_rows == 0 ||
      dimensions == 0 || rate_count == 0) {
    return -std::numeric_limits<float>::infinity();
  }

  float best_score = -std::numeric_limits<float>::infinity();
  std::size_t best_start = 0;
  std::size_t best_end = 0;
  float best_rate = 1.0F;

  for (std::size_t rate_index = 0; rate_index < rate_count; ++rate_index) {
    const float rate = playback_rates[rate_index];
    if (!std::isfinite(rate) || rate <= 0.0F) {
      continue;
    }
    const auto span = static_cast<std::size_t>(
        std::llround(static_cast<double>(query_rows - 1) * rate));
    if (span >= target_rows) {
      continue;
    }

    for (std::size_t start = 0; start + span < target_rows; ++start) {
      std::vector<float> frame_scores;
      frame_scores.reserve(query_rows);
      for (std::size_t query_row = 0; query_row < query_rows; ++query_row) {
        const auto target_offset = static_cast<std::size_t>(
            std::llround(static_cast<double>(query_row) * rate));
        const float frame_score = cosine(
            query + query_row * dimensions,
            target + (start + target_offset) * dimensions,
            dimensions);
        frame_scores.push_back(frame_score);
      }
      // Discard at most the lowest 25% of aligned samples. A codec-dropped
      // frame at a shot cut can otherwise overpower an exact multi-frame
      // sequence. Short sequences (<4 samples) retain every observation.
      const auto dropped = query_rows / 4;
      auto first_kept = frame_scores.begin() + static_cast<std::ptrdiff_t>(dropped);
      if (dropped) std::nth_element(frame_scores.begin(), first_kept, frame_scores.end());
      const float score = static_cast<float>(std::accumulate(first_kept, frame_scores.end(), 0.0)
          / static_cast<double>(query_rows - dropped));
      if (score > best_score) {
        best_score = score;
        best_start = start;
        best_end = start + span;
        best_rate = rate;
      }
    }
  }

  if (std::isfinite(best_score)) {
    *target_start_out = best_start;
    *target_end_out = best_end;
    *playback_rate_out = best_rate;
  }
  return best_score;
}
