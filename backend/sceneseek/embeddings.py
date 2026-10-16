from __future__ import annotations

import hashlib
import re
import threading
from collections.abc import Sequence
from typing import Protocol

import numpy as np
from numpy.typing import NDArray
from PIL import Image


FloatArray = NDArray[np.float32]


def _normalize(values: FloatArray) -> FloatArray:
    norms = np.linalg.norm(values, axis=1, keepdims=True)
    return values / np.maximum(norms, 1e-12)


class Embedder(Protocol):
    name: str
    dimensions: int

    def embed_text(self, texts: Sequence[str]) -> FloatArray: ...

    def embed_images(self, images: Sequence[Image.Image]) -> FloatArray: ...


class DeterministicEmbedder:
    """Fast offline backend for tests and development without model weights."""

    name = "deterministic-v1"
    dimensions = 64
    _colors = {
        "red": (1.0, 0.0, 0.0),
        "green": (0.0, 1.0, 0.0),
        "blue": (0.0, 0.0, 1.0),
        "yellow": (1.0, 1.0, 0.0),
        "purple": (0.6, 0.0, 0.8),
        "orange": (1.0, 0.4, 0.0),
        "white": (1.0, 1.0, 1.0),
        "black": (-1.0, -1.0, -1.0),
    }

    def embed_text(self, texts: Sequence[str]) -> FloatArray:
        output = np.zeros((len(texts), self.dimensions), dtype=np.float32)
        for row, text in enumerate(texts):
            tokens = re.findall(r"[a-z0-9]+", text.lower())
            for token in tokens:
                if token in self._colors:
                    output[row, :3] += self._colors[token]
                digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
                index = 3 + int.from_bytes(digest[:4], "little") % (self.dimensions - 3)
                output[row, index] += 1.0 if digest[4] % 2 else -1.0
            if not tokens:
                output[row, 3] = 1.0
        return _normalize(output)

    def embed_images(self, images: Sequence[Image.Image]) -> FloatArray:
        output = np.zeros((len(images), self.dimensions), dtype=np.float32)
        for row, image in enumerate(images):
            pixels = np.asarray(image.convert("RGB").resize((8, 8)), dtype=np.float32) / 255
            output[row, :3] = pixels.mean(axis=(0, 1))
            gray = pixels.mean(axis=2)
            output[row, 3 : 3 + 61] = gray.reshape(-1)[:61]
        return _normalize(output)


class ClipEmbedder:
    def __init__(self, model_id: str, device: str = "auto", revision: str | None = None):
        try:
            import torch
            from transformers import AutoProcessor, CLIPModel
        except ImportError as exc:
            raise RuntimeError(
                "CLIP embedding requires torch and transformers; install requirements.txt"
            ) from exc

        selected_device = (
            "cuda" if device == "auto" and torch.cuda.is_available() else device
        )
        if selected_device == "auto":
            selected_device = "cpu"
        self._torch = torch
        self._device = selected_device
        self._processor = AutoProcessor.from_pretrained(model_id, revision=revision)
        self._model = CLIPModel.from_pretrained(model_id, revision=revision).to(selected_device).eval()
        self._lock = threading.Lock()
        self.name = f"clip:{model_id}" + (f"@{revision}" if revision else "")
        self.dimensions = int(self._model.config.projection_dim)

    def embed_text(self, texts: Sequence[str]) -> FloatArray:
        inputs = self._processor(
            text=list(texts), return_tensors="pt", padding=True, truncation=True
        )
        inputs = {key: value.to(self._device) for key, value in inputs.items()}
        with self._lock, self._torch.inference_mode():
            values = self._model.get_text_features(**inputs)
        return _normalize(values.detach().cpu().float().numpy())

    def embed_images(self, images: Sequence[Image.Image]) -> FloatArray:
        inputs = self._processor(images=list(images), return_tensors="pt")
        inputs = {key: value.to(self._device) for key, value in inputs.items()}
        with self._lock, self._torch.inference_mode():
            values = self._model.get_image_features(**inputs)
        return _normalize(values.detach().cpu().float().numpy())


class LazyEmbedder:
    def __init__(self, kind: str, model_id: str, device: str, revision: str | None = None):
        self.kind = kind
        self.model_id = model_id
        self.device = device
        self.revision = revision
        self._instance: Embedder | None = None
        self._lock = threading.Lock()

    def get(self) -> Embedder:
        if self._instance is None:
            with self._lock:
                if self._instance is None:
                    if self.kind == "deterministic":
                        self._instance = DeterministicEmbedder()
                    elif self.kind == "clip":
                        self._instance = ClipEmbedder(self.model_id, self.device, self.revision)
                    else:
                        raise ValueError(
                            f"Unknown embedder {self.kind!r}; expected 'clip' or 'deterministic'"
                        )
        return self._instance

    @property
    def loaded(self) -> bool:
        return self._instance is not None

