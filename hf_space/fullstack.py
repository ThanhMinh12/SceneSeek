"""Real React + private FastAPI video library on the free ZeroGPU SDK."""
from __future__ import annotations

import os
import sys
import subprocess
import threading
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'backend'), str(ROOT/'hf_space')]
import spaces
import gradio as gr
from hf_space import app as models
from sceneseek.config import Settings
from sceneseek.main import create_app
from sceneseek.embeddings import ClipEmbedder


def main():
    hosted = os.getenv('SCENESEEK_SPACE_DEVICE', 'cuda') != 'cpu'
    os.environ['SCENESEEK_HOSTED'] = str(hosted).lower()
    os.environ['SCENESEEK_COOKIE_SECURE'] = str(hosted).lower()
    build = ROOT/'build'
    subprocess.run(['cmake', '-S', str(ROOT), '-B', str(build), '-DCMAKE_BUILD_TYPE=Release', '-DSCENESEEK_BUILD_TESTS=OFF'], check=True)
    subprocess.run(['cmake', '--build', str(build), '--parallel', '2'], check=True)
    models.MODEL = ClipEmbedder('openai/clip-vit-base-patch32', os.getenv('SCENESEEK_SPACE_DEVICE', 'cuda'),
                               '3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268')
    config = replace(Settings.from_env(), data_dir=Path(os.getenv('SCENESEEK_DATA_DIR', '/tmp/sceneseek-fullstack')),
                     frontend_dir=ROOT/'frontend/dist', max_video_seconds=60, max_upload_bytes=40*1024**2,
                     max_query_bytes=40*1024**2, frame_interval_seconds=1.0, browser_playback=True,
                     native_library=build/'libsceneseek_core.so')
    embedder = models.HostedEmbedder()
    embedder.loaded = True
    server = create_app(config, app_factory=gr.Server, queued_inference=True, embedder=embedder)
    def cleanup():
        while True:
            cutoff = datetime.now(UTC)-timedelta(hours=1)
            for video in server.state.database.list_videos():
                if video['status'] not in {'queued', 'processing'} and datetime.fromisoformat(video['created_at']) < cutoff:
                    try:
                        server.state.service.delete_video(video['id'])
                    except (KeyError, FileNotFoundError):
                        pass  # The owner may have removed this video meanwhile.
            threading.Event().wait(300)
    threading.Thread(target=cleanup, daemon=True).start()
    server.launch(server_name='0.0.0.0', server_port=int(os.getenv('PORT', '7860')),
                  max_file_size='40mb', show_error=False, ssr_mode=False, run_history=False, footer_links=[],
                  blocked_paths=[str(config.data_dir.resolve())])


if __name__ == '__main__':
    main()
