"""Browser regressions with controlled API fixtures, NOT CLIP inference.

Build frontend/, start Vite preview, then run:
  python scripts/smoke_ui.py --url http://127.0.0.1:4176
Requires Playwright and Chromium. Test uploads never reach a real backend.
"""
import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:4176')
    parser.add_argument('--screenshots', type=Path)
    args = parser.parse_args()
    if args.screenshots:
        args.screenshots.mkdir(parents=True, exist_ok=True)
    state = {'videos': [], 'polls': 0, 'runtime_requests': 0, 'uploads': 0, 'searches': []}
    video = {'id': 'ui-video', 'display_name': 'Practice video', 'original_filename': 'practice.mp4', 'status': 'processing', 'duration_seconds': .3, 'frame_count': 1, 'error': None, 'created_at': '2026-10-18T12:00:00Z'}
    job = {'id': 'ui-job', 'video_id': 'ui-video', 'status': 'queued', 'progress': 0, 'message': 'Preparing video', 'error': None}
    match = {'video_id': 'ui-video', 'title': 'Practice video', 'timestamp_seconds': 0, 'end_seconds': .3, 'score': .85, 'playback_rate': 1, 'thumbnail_url': '/api/thumbnails/ui-video/0.svg', 'video_url': '/api/videos/ui-video/stream'}
    media = b''

    def handle(route):
        path = urlparse(route.request.url).path
        method = route.request.method
        if path == '/api/runtime':
            state['runtime_requests'] += 1
            route.fulfill(json={'queued_inference': True, 'temporary': True, 'max_video_seconds': 60, 'max_upload_mb': 40, 'frame_interval_seconds': 1})
        elif path == '/api/health':
            route.fulfill(json={'status': 'ok', 'version': '0.1.0', 'similarity_backend': 'cpp', 'embedder': 'clip', 'model_loaded': True, 'indexed_videos': len(state['videos'])})
        elif path == '/api/videos' and method == 'POST':
            state['uploads'] += 1
            state['videos'] = [video]
            route.fulfill(status=202, json={'video': video, 'job': job})
        elif path == '/api/videos':
            route.fulfill(json=state['videos'])
        elif path == '/api/jobs/ui-job':
            state['polls'] += 1
            if state['polls'] > 1:
                job.update(status='complete', progress=1, message='Ready')
                video['status'] = 'ready'
            else:
                job.update(status='processing', progress=.5, message='Indexing video')
            route.fulfill(json=job)
        elif path.startswith('/api/search/'):
            mode = path.rsplit('/', 1)[-1]
            state['searches'].append(mode)
            query = route.request.post_data_json.get('query') if mode == 'text' else ''
            if query == 'server error':
                route.fulfill(status=503, json={'detail': 'The search worker is busy. Try again.'})
                return
            results = [] if query == 'nothing' else [{**match, 'playback_rate': 2 if mode == 'clip' else 1}]
            route.fulfill(json={'query_type': mode, 'elapsed_ms': 12, 'results': results})
        elif path.startswith('/api/thumbnails/'):
            route.fulfill(content_type='image/svg+xml', body='<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360"><rect width="640" height="360" fill="#586c88"/><circle cx="320" cy="180" r="65" fill="#c8a485"/></svg>')
        elif path == '/api/videos/ui-video/stream':
            route.fulfill(body=media, content_type='video/webm')
        elif path == '/api/videos/ui-video' and method == 'DELETE':
            state['videos'] = []
            route.fulfill(status=204)
        else:
            route.fulfill(status=404, json={'detail': 'Unknown fixture route'})

    def responsive(page, name):
        for width in (1440, 768, 390, 320):
            page.set_viewport_size({'width': width, 'height': 900})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), f'{name} overflows at {width}px'
            if args.screenshots and width in (1440, 390):
                page.screenshot(path=str(args.screenshots / f'sceneseek-{name}-{width}.png'), full_page=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={'width': 1440, 'height': 900}, reduced_motion='reduce')
        page.set_default_timeout(15000)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.route('**/api/**', handle)
        page.goto(args.url)
        expect(page.get_by_role('button', name='Choose video', exact=True)).to_be_visible()
        expect(page.get_by_role('textbox', name='Describe the scene to find')).to_have_count(0)
        responsive(page, 'empty')
        # Create a genuinely playable, tiny WebM in memory without model/FFmpeg dependencies.
        media = bytes(page.evaluate('''async () => {
          const canvas = document.createElement('canvas'); canvas.width = 160; canvas.height = 90;
          const context = canvas.getContext('2d'); context.fillStyle = '#586c88'; context.fillRect(0,0,160,90);
          const stream = canvas.captureStream(10); const recorder = new MediaRecorder(stream, {mimeType: 'video/webm;codecs=vp8'});
          const chunks = []; recorder.ondataavailable = event => chunks.push(event.data);
          const done = new Promise(resolve => recorder.onstop = resolve); recorder.start();
          const timer = setInterval(() => {context.fillStyle = '#586c88'; context.fillRect(0,0,160,90);}, 50);
          await new Promise(resolve => setTimeout(resolve, 350)); recorder.stop(); await done;
          clearInterval(timer); stream.getTracks().forEach(track => track.stop());
          return Array.from(new Uint8Array(await new Blob(chunks).arrayBuffer()));
        }'''))
        assert len(media) > 100
        page.get_by_label('Upload video', exact=True).set_input_files({'name': 'wrong.txt', 'mimeType': 'text/plain', 'buffer': b'invalid'})
        expect(page.get_by_role('alert')).to_contain_text('Choose an MP4')
        assert state['uploads'] == 0
        page.get_by_label('Upload video', exact=True).set_input_files({'name': 'practice.mp4', 'mimeType': 'video/mp4', 'buffer': b'controlled upload fixture'})
        expect(page.get_by_role('button', name='Search', exact=True)).to_be_disabled()
        expect(page.get_by_role('progressbar')).to_be_visible()
        expect(page.get_by_text('Ready to search', exact=False)).to_be_visible(timeout=20000)
        page.get_by_role('textbox', name='Describe the scene to find').fill('red car')
        page.get_by_role('button', name='Search', exact=True).click()
        expect(page.locator('.result-card')).to_have_count(1)
        expect(page.locator('.library')).not_to_have_attribute('open', '')
        responsive(page, 'results')
        page.locator('.result-visual').first.click()
        expect(page.get_by_role('dialog')).to_be_visible()
        page.wait_for_function('document.querySelector("video").readyState >= 2')
        assert page.locator('video').evaluate('video => video.error === null')
        expect(page.get_by_role('button', name='Close player')).to_be_focused()
        page.keyboard.press('Escape')
        expect(page.get_by_role('dialog')).to_have_count(0)
        expect(page.locator('.result-visual').first).to_be_focused()
        page.get_by_role('button', name='Image', exact=True).click()
        expect(page.get_by_role('button', name='Search', exact=True)).to_be_disabled()
        page.get_by_label('Upload reference image').set_input_files({'name': 'reference.png', 'mimeType': 'image/png', 'buffer': b'controlled image fixture'})
        page.get_by_role('button', name='Search', exact=True).click()
        expect(page.locator('.result-card')).to_have_count(1)
        page.get_by_role('button', name='Video clip', exact=True).click()
        page.get_by_label('Upload reference clip').set_input_files({'name': 'reference.webm', 'mimeType': 'video/webm', 'buffer': media})
        page.get_by_role('button', name='Search', exact=True).click()
        expect(page.get_by_text('Matched at 2× speed')).to_be_visible()
        page.get_by_role('button', name='Text', exact=True).click()
        page.get_by_role('textbox', name='Describe the scene to find').fill('nothing')
        page.get_by_role('button', name='Search', exact=True).click()
        expect(page.get_by_role('heading', name='No matching moments')).to_be_visible()
        page.get_by_role('textbox', name='Describe the scene to find').fill('server error')
        page.get_by_role('button', name='Search', exact=True).click()
        expect(page.get_by_role('alert')).to_contain_text('search worker is busy')
        page.locator('.library > summary').click()
        expect(page.get_by_role('button', name='Remove Practice video')).to_be_visible()
        responsive(page, 'library')
        page.on('dialog', lambda dialog: dialog.accept())
        page.get_by_role('button', name='Remove Practice video').click()
        expect(page.get_by_role('button', name='Choose video', exact=True)).to_be_visible()
        assert state['searches'] == ['text', 'image', 'clip', 'text', 'text'], state
        assert state['runtime_requests'] == 1, state
        assert not errors, errors
        browser.close()
    print(json.dumps({'status': 'passed', 'controlled_api_fixtures': True, 'real_model_inference': False, 'widths': [1440, 768, 390, 320], 'checks': ['simple empty state', 'file validation', 'upload', 'progress', 'text search', 'image search', 'clip search', 'playable video', 'keyboard dialog', 'empty results', 'server error', 'mobile deletion', 'single session bootstrap']}))


if __name__ == '__main__':
    main()
