#pragma once

#include <cstddef>
#include <cstdint>

#if defined(_WIN32)
#define SCENESEEK_EXPORT __declspec(dllexport)
#else
#define SCENESEEK_EXPORT __attribute__((visibility("default")))
#endif

extern "C" {

// Returns the number of results written. Results are ordered by descending
// cosine similarity, then ascending source index for deterministic ties.
SCENESEEK_EXPORT std::size_t ss_top_k_cosine(
    const float* query,
    const float* matrix,
    std::size_t rows,
    std::size_t dimensions,
    std::size_t k,
    std::int64_t* indices_out,
    float* scores_out);

// Finds the best contiguous sequence match across a caller-supplied set of
// frame-spacing hypotheses. Query and target rows are embedding vectors.
// The service maps physical playback rates to this temporal grid. Scores are
// mean aligned cosine similarity after dropping up to the lowest 25% of samples.
// Returns negative infinity on invalid input or when no rate fits.
SCENESEEK_EXPORT float ss_best_sequence_match(
    const float* query,
    std::size_t query_rows,
    const float* target,
    std::size_t target_rows,
    std::size_t dimensions,
    const float* playback_rates,
    std::size_t rate_count,
    std::size_t* target_start_out,
    std::size_t* target_end_out,
    float* playback_rate_out);

}

