"""Real-model video/text/image/normal-slow-fast clip regression checks.

Pass a prepared fixture directory containing trailer.mp4 (first 30 seconds of
the Big Buck Bunny trailer), frame12.jpg, query.mp4 (seconds 10–18),
query-slow.mp4 (half speed), and query-fast.mp4 (double speed).
"""
import argparse
import json
import time
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('media', type=Path)
    parser.add_argument('--url', default='http://127.0.0.1:8000')
    parser.add_argument('--browser', action='store_true')
    args = parser.parse_args()
    report = {'real_model':True}
    with httpx.Client(base_url=args.url, timeout=180) as client:
        deadline = time.monotonic() + 30
        while True:
            try:
                if client.get('/api/health').status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if time.monotonic() >= deadline:
                raise TimeoutError('API did not become healthy within 30 seconds')
            time.sleep(.5)
        with (args.media / 'trailer.mp4').open('rb') as handle:
            response = client.post('/api/videos', files={'file':('trailer.mp4', handle, 'video/mp4')})
        response.raise_for_status()
        video_id = response.json()['video']['id']
        job_id = response.json()['job']['id']
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            response = client.get('/api/jobs/' + job_id)
            response.raise_for_status()
            job = response.json()
            if job['status'] in {'complete','failed'}:
                break
            time.sleep(1)
        assert job['status'] == 'complete', job.get('error') or job['status']
        health = client.get('/api/health').json()
        assert health['embedder'] == 'clip' and health['similarity_backend'] == 'cpp' and health['model_loaded']
        report['runtime'] = health
        response = client.post('/api/search/text', json={'query':'an animated rabbit in a forest','top_k':3})
        response.raise_for_status()
        assert response.json()['results']
        report['text_results'] = len(response.json()['results'])
        for name, kind, expected_rate in [('frame12.jpg','image',None),('query.mp4','clip',1),('query-slow.mp4','clip',.5),('query-fast.mp4','clip',2)]:
            with (args.media / name).open('rb') as handle:
                response = client.post('/api/search/' + kind, files={'file':(name, handle)})
            response.raise_for_status()
            result = response.json()['results'][0]
            assert result['video_id'] == video_id
            report[name] = result
            if expected_rate is None:
                assert abs(result['timestamp_seconds'] - 12) <= .1, result
            else:
                assert abs(result['timestamp_seconds'] - 10) <= 2, (name, result)
                assert abs(result['end_seconds'] - 18) <= 2, (name, result)
                assert abs(result['playback_rate'] - expected_rate) <= .01, (name, result)
        stream = client.get(f'/api/videos/{video_id}/stream', headers={'Range':'bytes=0-1023'})
        assert stream.status_code == 206 and 'video/webm' in stream.headers['content-type']
        with httpx.Client(base_url=args.url) as stranger:
            assert stranger.get('/api/videos').json() == []
            assert stranger.get(f'/api/videos/{video_id}/stream').status_code == 404
        report['session_isolation'] = 'passed'
        if args.browser:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                context = browser.new_context(viewport={'width':1440,'height':1000})
                context.add_cookies([{'name':cookie.name,'value':cookie.value,'url':args.url} for cookie in client.cookies.jar])
                page = context.new_page()
                page.goto(args.url)
                page.get_by_role('textbox', name='Describe the scene to find').fill('an animated rabbit in a forest')
                page.locator('.search-button').click()
                page.locator('.result-visual').first.click(timeout=30000)
                page.wait_for_function('() => document.querySelector("video")?.readyState >= 2', timeout=30000)
                player = page.locator('video').evaluate('video => ({duration:video.duration,error:video.error})')
                assert abs(player['duration'] - 30) < .2 and player['error'] is None, player
                screenshot = Path('/tmp/projects-ready-evidence/sceneseek-player.png')
                screenshot.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(screenshot))
                report['browser_playback'] = player
                browser.close()
        print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
