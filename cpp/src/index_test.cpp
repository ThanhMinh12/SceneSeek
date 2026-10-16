#include "sceneseek/index.h"

#ifdef NDEBUG
#undef NDEBUG
#endif
#include <array>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <iostream>

int main() {
  {
    constexpr std::array<float, 2> query{1.0F, 0.0F};
    constexpr std::array<float, 8> matrix{
        0.0F, 1.0F,
        0.7F, 0.7F,
        1.0F, 0.0F,
        -1.0F, 0.0F};
    std::array<std::int64_t, 2> indices{};
    std::array<float, 2> scores{};
    const auto count = ss_top_k_cosine(
        query.data(), matrix.data(), 4, 2, 2, indices.data(), scores.data());
    assert(count == 2);
    assert(indices[0] == 2);
    assert(indices[1] == 1);
    assert(scores[0] > scores[1]);
  }

  {
    constexpr std::array<float, 6> query{
        1.0F, 0.0F,
        0.0F, 1.0F,
        -1.0F, 0.0F};
    constexpr std::array<float, 14> target{
        0.0F, -1.0F,
        1.0F, 0.0F,
        0.2F, 0.8F,
        0.0F, 1.0F,
        -0.8F, 0.2F,
        -1.0F, 0.0F,
        0.0F, -1.0F};
    constexpr std::array<float, 2> rates{1.0F, 2.0F};
    std::size_t start = 0;
    std::size_t end = 0;
    float rate = 0.0F;
    const float score = ss_best_sequence_match(
        query.data(), 3, target.data(), 7, 2, rates.data(), rates.size(),
        &start, &end, &rate);
    assert(score > 0.99F);
    assert(start == 1);
    assert(end == 5);
    assert(std::abs(rate - 2.0F) < 0.001F);
  }

  std::cout << "SceneSeek native tests passed\n";
  return 0;
}

