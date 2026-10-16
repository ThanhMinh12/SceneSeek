from __future__ import annotations

import ctypes
import math
import os
from pathlib import Path

import numpy as np
from numpy.typing import NDArray


FloatArray = NDArray[np.float32]


class SimilarityIndex:
    def __init__(self, library_path: Path | None = None):
        self._library: ctypes.CDLL | None = None
        candidates: list[Path] = []
        if library_path:
            candidates.append(library_path)
        if env_path := os.getenv("SCENESEEK_NATIVE_LIBRARY"):
            candidates.append(Path(env_path))
        repo_root = Path(__file__).resolve().parents[2]
        candidates.extend(
            [
                repo_root / "build" / "libsceneseek_core.so",
                repo_root / "build" / "Release" / "sceneseek_core.dll",
                repo_root / "build" / "libsceneseek_core.dylib",
            ]
        )
        for candidate in candidates:
            if candidate.exists():
                self._library = ctypes.CDLL(str(candidate))
                self._configure()
                break

    @property
    def backend(self) -> str:
        return "cpp" if self._library is not None else "numpy"

    def _configure(self) -> None:
        assert self._library is not None
        float_pointer = ctypes.POINTER(ctypes.c_float)
        self._library.ss_top_k_cosine.argtypes = [
            float_pointer,
            float_pointer,
            ctypes.c_size_t,
            ctypes.c_size_t,
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_int64),
            float_pointer,
        ]
        self._library.ss_top_k_cosine.restype = ctypes.c_size_t
        self._library.ss_best_sequence_match.argtypes = [
            float_pointer,
            ctypes.c_size_t,
            float_pointer,
            ctypes.c_size_t,
            ctypes.c_size_t,
            float_pointer,
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_size_t),
            ctypes.POINTER(ctypes.c_size_t),
            ctypes.POINTER(ctypes.c_float),
        ]
        self._library.ss_best_sequence_match.restype = ctypes.c_float

    @staticmethod
    def _matrix(value: FloatArray) -> FloatArray:
        matrix = np.ascontiguousarray(value, dtype=np.float32)
        if matrix.ndim != 2:
            raise ValueError("Expected a two-dimensional embedding matrix")
        return matrix

    def top_k(
        self, query: FloatArray, matrix: FloatArray, k: int
    ) -> list[tuple[int, float]]:
        target = self._matrix(matrix)
        vector = np.ascontiguousarray(query, dtype=np.float32).reshape(-1)
        if target.shape[0] == 0 or k <= 0:
            return []
        if vector.shape[0] != target.shape[1]:
            raise ValueError("Query and index embedding dimensions do not match")
        count = min(k, target.shape[0])

        if self._library is not None:
            indices = np.empty(count, dtype=np.int64)
            scores = np.empty(count, dtype=np.float32)
            written = self._library.ss_top_k_cosine(
                vector.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                target.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                target.shape[0],
                target.shape[1],
                count,
                indices.ctypes.data_as(ctypes.POINTER(ctypes.c_int64)),
                scores.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
            )
            return [(int(indices[i]), float(scores[i])) for i in range(written)]

        vector_norm = np.linalg.norm(vector)
        row_norms = np.linalg.norm(target, axis=1)
        denominator = np.maximum(row_norms * vector_norm, 1e-12)
        scores = (target @ vector) / denominator
        order = np.lexsort((np.arange(len(scores)), -scores))[:count]
        return [(int(index), float(scores[index])) for index in order]

    def best_sequence(
        self,
        query: FloatArray,
        target: FloatArray,
        rates: tuple[float, ...] = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0),
    ) -> tuple[float, int, int, float] | None:
        query_matrix = self._matrix(query)
        target_matrix = self._matrix(target)
        if (
            query_matrix.shape[0] == 0
            or target_matrix.shape[0] == 0
            or query_matrix.shape[1] != target_matrix.shape[1]
        ):
            return None
        rate_array = np.ascontiguousarray(rates, dtype=np.float32)

        if self._library is not None:
            start = ctypes.c_size_t()
            end = ctypes.c_size_t()
            rate = ctypes.c_float()
            score = float(
                self._library.ss_best_sequence_match(
                    query_matrix.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                    query_matrix.shape[0],
                    target_matrix.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                    target_matrix.shape[0],
                    target_matrix.shape[1],
                    rate_array.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                    len(rate_array),
                    ctypes.byref(start),
                    ctypes.byref(end),
                    ctypes.byref(rate),
                )
            )
            if not math.isfinite(score):
                return None
            return score, start.value, end.value, float(rate.value)

        query_norm = query_matrix / np.maximum(
            np.linalg.norm(query_matrix, axis=1, keepdims=True), 1e-12
        )
        target_norm = target_matrix / np.maximum(
            np.linalg.norm(target_matrix, axis=1, keepdims=True), 1e-12
        )
        best: tuple[float, int, int, float] | None = None
        for rate in rates:
            if not math.isfinite(rate) or rate <= 0:
                continue
            # Match C++ llround (half away from zero), not Python/NumPy's
            # half-to-even rounding. All offsets are nonnegative.
            rate = float(np.float32(rate))
            span = math.floor((len(query_norm) - 1) * rate + 0.5)
            if span >= len(target_norm):
                continue
            offsets = np.floor(np.arange(len(query_norm), dtype=np.float64) * rate + 0.5).astype(int)
            for start in range(0, len(target_norm) - span):
                frame_scores = np.sum(query_norm * target_norm[start + offsets], axis=1)
                dropped = len(frame_scores) // 4
                score = float(np.mean(np.sort(frame_scores)[dropped:]))
                if best is None or score > best[0]:
                    best = (score, start, start + span, rate)
        return best

