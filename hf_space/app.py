"""ZeroGPU entry point. The full React/FastAPI application is separate."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT / 'hf_space'))
os.environ.setdefault('OMP_NUM_THREADS', '2')
os.environ.setdefault('TOKENIZERS_PARALLELISM', 'false')

import spaces  # Must be imported before torch/transformers on ZeroGPU.
import gradio as gr
from sceneseek.embeddings import ClipEmbedder
from demo import DemoSessions

MODEL = None


@spaces.GPU(duration=15)
def embed_text(texts):
    return MODEL.embed_text(texts)


@spaces.GPU(duration=30)
def embed_images(images):
    return MODEL.embed_images(images)


class HostedEmbedder:
    def get(self):
        return self

    @property
    def name(self):
        return MODEL.name

    def embed_text(self, texts):
        return embed_text(texts)

    def embed_images(self, images):
        return embed_images(images)


def build_app(store):
    def guarded(fn, *args):
        try:
            return fn(*args)
        except (ValueError, RuntimeError) as exc:
            raise gr.Error(str(exc)) from exc

    with gr.Blocks(title='SceneSeek', delete_cache=(300, 3600)) as demo:
        state = gr.State(value=store.new, time_to_live=3600, delete_callback=store.delete)
        gr.Markdown('# SceneSeek\nFind a moment with text, an image, or a clip.')
        gr.Markdown('Free GPU demo · Queues and daily limits apply. Use non-sensitive media only; preview links are shareable. Sessions expire after an hour or restart.')
        with gr.Row():
            with gr.Column():
                upload = gr.File(label='1. Add a video · up to 60 seconds / 40 MB', file_types=['video'])
                index = gr.Button('Index video', variant='primary')
                library = gr.Dataframe(headers=['Video', 'Seconds', 'Frames'], interactive=False, label='Your temporary library')
                clear = gr.Button('Clear library')
            original = gr.Video(label='Indexed video', interactive=False)
        message = gr.Markdown()
        gr.Markdown('## 2. Search your library')
        with gr.Tabs():
            with gr.Tab('Text'):
                text = gr.Textbox(label='Describe a scene', placeholder='A rabbit in a grassy field', max_length=500)
                text_button = gr.Button('Search text')
            with gr.Tab('Image'):
                image = gr.Image(label='Reference image', type='filepath')
                image_button = gr.Button('Search image')
            with gr.Tab('Clip'):
                clip = gr.File(label='Reference clip · 4–60 seconds / 40 MB', file_types=['video'])
                clip_button = gr.Button('Match sequence')
        gallery = gr.Gallery(label='Matching moments', columns=3, object_fit='contain', interactive=False)
        results = gr.Dataframe(headers=['Video', 'Start (s)', 'End (s)', 'Rate (×)', 'Cosine similarity'], interactive=False, label='Results')
        playback = gr.Video(label='Best matching segment', interactive=False)
        status = gr.Markdown()
        gr.Markdown('[Full React/FastAPI source](https://github.com/ThanhMinh12/SceneSeek) · [Thanh’s portfolio](https://thanhminh12.github.io/)')
        opts = dict(concurrency_id='scene-demo', concurrency_limit=1)
        index.click(lambda s, f: guarded(store.index, s, f), [state, upload], [library, original, message], api_name='index_video', **opts)
        for button, kind, field in [(text_button, 'text', text), (image_button, 'image', image), (clip_button, 'clip', clip)]:
            def search(s, q, mode=kind):
                return guarded(store.search, s, mode, q)
            button.click(search, [state, field], [gallery, results, playback, status], api_name=f'search_{kind}', **opts)
        def reset(s):
            store.delete(s)
            return store.new(), [], None, 'Library cleared.', [], [], None, ''
        clear.click(reset, [state], [state, library, original, message, gallery, results, playback, status], api_name='clear_library', **opts)
    return demo.queue(max_size=12, default_concurrency_limit=1)


if __name__ == '__main__':
    build = ROOT / 'build'
    subprocess.run(['cmake', '-S', str(ROOT), '-B', str(build), '-DCMAKE_BUILD_TYPE=Release', '-DSCENESEEK_BUILD_TESTS=OFF'], check=True)
    subprocess.run(['cmake', '--build', str(build), '--parallel', '2'], check=True)
    # Root startup placement is required by ZeroGPU's CUDA emulation.
    MODEL = ClipEmbedder('openai/clip-vit-base-patch32', os.getenv('SCENESEEK_SPACE_DEVICE', 'cuda'), '3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268')
    store = DemoSessions(Path('/tmp/sceneseek-demo-sessions'), HostedEmbedder(), build / 'libsceneseek_core.so')
    build_app(store).launch(server_name='0.0.0.0', server_port=int(os.getenv('PORT', '7860')), max_file_size='40mb', show_error=False)
