"""Ownership/shape-safe bridge to the C++ catalog; no ranking in Python."""
from __future__ import annotations

import ctypes as C
import weakref
from pathlib import Path

import numpy as np


class Video(C.Structure):
    _fields_ = [('id', C.c_char_p), ('duration_seconds', C.c_double)]


class Match(C.Structure):
    _fields_ = [('video_index', C.c_size_t), ('frame', C.c_uint64),
                ('timestamp_seconds', C.c_double), ('end_seconds', C.c_double),
                ('score', C.c_float), ('playback_rate', C.c_float), ('thumbnail', C.c_char * 192)]


class Stats(C.Structure):
    _fields_ = [(name, C.c_uint64) for name in
                ('cached_bytes', 'cache_limit', 'cached_shards', 'cache_hits', 'cache_misses', 'skipped_shards')]


def encoded(value: str) -> bytes:
    if not isinstance(value, str) or '\0' in value:
        raise ValueError('Native strings cannot contain NUL characters')
    return value.encode('utf-8')


class NativeEngine:
    def __init__(self, library, directory: Path, cache_bytes: int = 64*1024**2, workers: int = 2):
        self.library = library
        try:
            library.ss_engine_abi_version.restype = C.c_uint32
            if library.ss_engine_abi_version() != 1:
                raise RuntimeError('Unsupported SceneSeek engine ABI; rebuild the C++ library')
        except AttributeError as error:
            raise RuntimeError('Rebuild the SceneSeek C++ library to enable the native catalog') from error
        fp, dp = C.POINTER(C.c_float), C.POINTER(C.c_double)
        library.ss_engine_last_error.restype = C.c_char_p
        library.ss_engine_create.argtypes = [C.c_char_p, C.c_uint64, C.c_size_t]
        library.ss_engine_create.restype = C.c_void_p
        library.ss_engine_destroy.argtypes = [C.c_void_p]
        library.ss_engine_destroy.restype = None
        library.ss_engine_save.argtypes = [C.c_void_p, C.c_char_p, C.c_char_p, fp, C.c_size_t, C.c_size_t, dp, C.POINTER(C.c_char_p)]
        library.ss_engine_save.restype = C.c_int
        library.ss_engine_remove.argtypes = [C.c_void_p, C.c_char_p]
        library.ss_engine_remove.restype = C.c_int
        library.ss_engine_get_stats.argtypes = [C.c_void_p, C.POINTER(Stats)]
        library.ss_engine_get_stats.restype = C.c_int
        common = [C.c_char_p, C.POINTER(Video), C.c_size_t, C.c_size_t, C.POINTER(Match), C.c_size_t]
        library.ss_engine_search_frames.argtypes = [C.c_void_p, fp, C.c_size_t] + common
        library.ss_engine_search_frames.restype = C.c_int64
        library.ss_engine_search_sequence.argtypes = [C.c_void_p, fp, C.c_size_t, C.c_size_t, dp, C.c_double] + common
        library.ss_engine_search_sequence.restype = C.c_int64
        if not 0 <= cache_bytes <= 4*1024**3 or not 1 <= workers <= 8:
            raise ValueError('Invalid native cache budget or worker count')
        self.handle = library.ss_engine_create(encoded(str(directory)), cache_bytes, workers)
        if not self.handle:
            self._error()
        self._finalizer = weakref.finalize(self, library.ss_engine_destroy, self.handle)

    def close(self):
        self._finalizer()
        self.handle = None

    def _error(self):
        raise ValueError((self.library.ss_engine_last_error() or b'Native engine failure').decode('utf-8', errors='replace'))

    def _open(self):
        if self.handle is None:
            raise RuntimeError('Native engine is closed')

    @staticmethod
    def _matrix(values):
        matrix = np.ascontiguousarray(values, dtype=np.float32)
        if matrix.ndim != 2 or not 0 < matrix.shape[0] <= 1_000_000 or not 0 < matrix.shape[1] <= 16384:
            raise ValueError('Invalid native embedding matrix shape')
        return matrix

    def save(self, video_id, embeddings, timestamps, thumbnails, model):
        self._open()
        matrix = self._matrix(embeddings)
        times = np.ascontiguousarray(timestamps, dtype=np.float64)
        if times.shape != (len(matrix),) or len(thumbnails) != len(matrix):
            raise ValueError('Index metadata length mismatch')
        names = (C.c_char_p * len(thumbnails))(*[encoded(str(name)) for name in thumbnails])
        status = self.library.ss_engine_save(self.handle, encoded(video_id), encoded(model),
            matrix.ctypes.data_as(C.POINTER(C.c_float)), *matrix.shape,
            times.ctypes.data_as(C.POINTER(C.c_double)), names)
        if status < 0:
            self._error()

    def remove(self, video_id):
        self._open()
        if self.library.ss_engine_remove(self.handle, encoded(video_id)) < 0:
            self._error()

    def stats(self):
        self._open()
        output = Stats()
        if self.library.ss_engine_get_stats(self.handle, C.byref(output)) < 0:
            self._error()
        return {name: int(getattr(output, name)) for name, _ in Stats._fields_}

    def search(self, query, model, videos, top_k, *, timestamps=None, duration=None, sequence=False):
        self._open()
        if not 1 <= top_k <= 50:
            raise ValueError('top_k must be between 1 and 50')
        allowed = (Video * len(videos))(*[Video(encoded(video['id']), float(video.get('duration_seconds') or 0)) for video in videos])
        output = (Match * top_k)()
        common = [encoded(model), allowed, len(videos), top_k, output, top_k]
        if sequence:
            matrix = self._matrix(query)
            times = None if timestamps is None else np.ascontiguousarray(timestamps, dtype=np.float64)
            if times is not None and times.shape != (len(matrix),):
                raise ValueError('Query timestamp length mismatch')
            count = self.library.ss_engine_search_sequence(self.handle,
                matrix.ctypes.data_as(C.POINTER(C.c_float)), *matrix.shape,
                times.ctypes.data_as(C.POINTER(C.c_double)) if times is not None else None,
                float(duration) if duration is not None else 0, *common)
        else:
            vector = np.ascontiguousarray(query, dtype=np.float32)
            if vector.ndim != 1:
                raise ValueError('Expected a one-dimensional query vector')
            count = self.library.ss_engine_search_frames(self.handle,
                vector.ctypes.data_as(C.POINTER(C.c_float)), len(vector), *common)
        if count < 0:
            self._error()
        return [(videos[match.video_index], match) for match in output[:count]]
