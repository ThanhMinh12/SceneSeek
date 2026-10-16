import numpy as np

from sceneseek.native import SimilarityIndex


def test_top_k_orders_cosine_similarity() -> None:
    index = SimilarityIndex()
    query = np.array([1.0, 0.0], dtype=np.float32)
    matrix = np.array(
        [[0.0, 1.0], [0.7, 0.7], [1.0, 0.0], [-1.0, 0.0]], dtype=np.float32
    )

    results = index.top_k(query, matrix, 3)

    assert [item[0] for item in results] == [2, 1, 0]
    assert results[0][1] > results[1][1] > results[2][1] - 1e-6


def test_sequence_search_finds_rate_adjusted_span() -> None:
    index = SimilarityIndex()
    query = np.array([[1, 0], [0, 1], [-1, 0]], dtype=np.float32)
    target = np.array(
        [[0, -1], [1, 0], [0.2, 0.8], [0, 1], [-0.8, 0.2], [-1, 0], [0, -1]],
        dtype=np.float32,
    )

    result = index.best_sequence(query, target, rates=(1.0, 2.0))

    assert result is not None
    score, start, end, rate = result
    assert score > 0.99
    assert (start, end, rate) == (1, 5, 2.0)

