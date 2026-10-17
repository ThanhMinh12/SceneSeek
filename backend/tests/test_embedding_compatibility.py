from contextlib import nullcontext
from types import SimpleNamespace
import threading

import numpy as np
import pytest

from sceneseek.embeddings import ClipEmbedder


class TensorResult:
    def detach(self):
        return self

    cpu = float = detach

    def numpy(self):
        return np.array([[3, 4, 0]], dtype=np.float32)


@pytest.mark.parametrize('modern', [False, True])
@pytest.mark.parametrize('kind', ['text', 'image'])
def test_projected_features_support_transformers_4_and_5(modern, kind):
    tensor = TensorResult()
    result = SimpleNamespace(pooler_output=tensor) if modern else tensor
    model = ClipEmbedder.__new__(ClipEmbedder)
    model._model = SimpleNamespace(get_text_features=lambda **kw: result, get_image_features=lambda **kw: result)
    model._processor = lambda **kw: {}
    model._torch = SimpleNamespace(inference_mode=nullcontext)
    model._lock = threading.Lock()
    model._device = 'cpu'
    values = model.embed_text(['test']) if kind == 'text' else model.embed_images([object()])
    np.testing.assert_allclose(values, [[0.6, 0.8, 0]], atol=1e-6)
