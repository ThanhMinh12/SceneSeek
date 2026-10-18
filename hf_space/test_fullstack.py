import gradio as gr
import pytest
from dataclasses import replace
from pathlib import Path
from shutil import copyfile
from fastapi.testclient import TestClient

from sceneseek.main import create_app
from backend.tests.test_api import make_settings


def test_hosted_branding_uses_the_mounted_asset_route(tmp_path):
    frontend = tmp_path / 'frontend'
    (frontend / 'assets').mkdir(parents=True)
    copyfile(Path(__file__).resolve().parents[1] / 'frontend/public/assets/brandmark.svg', frontend / 'assets/brandmark.svg')
    (frontend / 'index.html').write_text('<img src="/assets/brandmark.svg" alt="SceneSeek">')
    settings = replace(make_settings(tmp_path), frontend_dir=frontend)
    app = create_app(settings, app_factory=gr.Server, queued_inference=True)
    with TestClient(app) as client:
        assert client.get('/').status_code == 200
        logo = client.get('/assets/brandmark.svg')
        assert logo.status_code == 200
        assert 'image/svg+xml' in logo.headers['content-type']
        assert '<svg' in logo.text
        assert client.get('/brandmark.svg').status_code == 404


def test_queued_index_then_owned_search_and_replay_denial(tmp_path):
    app = create_app(make_settings(tmp_path), app_factory=gr.Server, queued_inference=True)
    handlers = {kw['api_name']: fn for fn,kw in app._deferred_apis}
    def index(job_id, video_id):
        app.state.database.update_video(video_id, status='ready')
        app.state.database.update_job(job_id, status='complete')
    app.state.service.index_video = index
    app.state.service.text_search = lambda query, top_k, owner: []
    with TestClient(app) as owner, TestClient(app) as foreign:
        created = owner.post('/api/videos', files={'file': ('video.mp4', b'unit fixture')})
        assert created.status_code == 202
        value = created.json()
        token = value['dispatch']['token']
        assert owner.get('/api/videos').json()[0]['status'] == 'queued'
        assert foreign.get('/api/videos').json() == []
        foreign.post('/api/dispatch/cancel', json={'token': token})
        assert handlers['run_index'](token)['status'] == 'complete'
        with pytest.raises(ValueError):
            handlers['run_index'](token)
        ticket = owner.post('/api/search/text', json={'query': 'rabbit'}).json()
        assert handlers['run_search'](ticket['dispatch']['token'])['results'] == []
        assert foreign.get('/api/jobs/'+value['job']['id']).status_code == 404
