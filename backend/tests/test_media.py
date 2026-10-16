from pathlib import Path

import cv2
import numpy as np

from sceneseek.media import extract_frames


def test_fractional_frame_stride_does_not_accumulate_timestamp_drift(tmp_path: Path):
    path = tmp_path / '25fps.avi'
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'MJPG'), 25, (64,48))
    assert writer.isOpened()
    for frame in range(250): writer.write(np.full((48,64,3), frame % 255, dtype=np.uint8))
    writer.release()
    frames = extract_frames(path, .5)
    assert len(frames.timestamps) == 20
    expected = np.arange(20) * .5
    assert np.max(np.abs(np.asarray(frames.timestamps) - expected)) <= .021
