"""Foreground browser acceptance and sanitized captures for redesign slice 3.

Requires the optional playwright package and installed Chromium. No gateway is
started: API fixtures are intercepted in the browser, using the shipped bundle.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "design/redesign-v1/evidence-s3"


def main():
    OUT.mkdir(exist_ok=True)
    now = datetime.now(timezone.utc)
    stamp = lambda minutes: (now - timedelta(minutes=minutes)).isoformat()
    jobs = [
        {"id":"fixture-gate", "title":"Publish release notes?", "status":"needs_approval"},
        {"id":"fixture-review", "title":"Check the changes", "status":"in_progress", "started_at":stamp(2),
         "leased_by_instance_id":"reviewer", "target_agent_role":"Reviewer",
         "output_payload":{"progress":"Reading the changes to the install page."},
         "input_payload":{"score":{"run_id":"fixture-run", "score_id":"Weekly release", "task":"review", "attempt":2}}},
        {"id":"fixture-stuck", "title":"Fix the install page", "status":"in_progress", "started_at":stamp(12),
         "leased_by_instance_id":"fixer", "target_agent_role":"Fixer",
         "input_payload":{"score":{"run_id":"fixture-run", "score_id":"Weekly release", "task":"fix"}}},
    ]
    agents = [{"instance_id":"reviewer", "role":"reviewer", "name":"Reviewer", "status":"online", "last_seen_at":stamp(1)}]
    run = {"title":"Weekly release", "tasks":[
        {"id":"research", "title":"Research"}, {"id":"review", "title":"Review", "on_reject":"fix"},
        {"id":"fix", "title":"Fix", "depends_on":["review"]}, {"id":"publish", "title":"Publish", "depends_on":["review"]}],
        "dispatch":[{"task":"review", "phase":"review", "job_id":"fixture-review", "status":"dispatched"},
                    {"task":"fix", "phase":"work", "job_id":"fixture-stuck", "status":"dispatched"}], "jobs":jobs[1:]}
    requests = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for name, viewport, theme in [("desktop-light", {"width":1280,"height":900}, "light"),
                                          ("phone-dark", {"width":390,"height":844}, "dark")]:
                context = browser.new_context(viewport=viewport, color_scheme=theme, reduced_motion="reduce")
                try:
                    page = context.new_page()
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.add_init_script("localStorage.setItem('bitcadence_page','overview'); localStorage.setItem('bitcadence_conn',JSON.stringify({url:'http://fixture.test',token:'fixture'}));")
                    def intercept(route):
                        path = urlsplit(route.request.url).path
                        requests.append((route.request.method, route.request.url))
                        if path == '/api/agents': data = agents
                        elif path == '/api/jobs':
                            assert 'limit=200' in route.request.url
                            data = jobs
                        elif path == '/api/score/autonomy/runs/fixture-run': data = run
                        else: data = []
                        route.fulfill(status=200, content_type='application/json', body=json.dumps(data))
                    page.route('http://fixture.test/**', intercept)
                    page.goto((ROOT/'src/mco/static/console.html').as_uri())
                    page.get_by_role('heading', name='What needs you').wait_for()
                    page.get_by_role('button', name='Weekly release').wait_for()
                    home = page.locator('.home-view').inner_text()
                    assert home.index('What needs you') < home.index("What's running")
                    assert 'fixture-' not in home
                    assert 'No sign of life for 10 minutes' in home
                    page.get_by_text('Step 2 of 4', exact=True).wait_for()
                    home = page.locator('.home-view').inner_text()
                    assert page.get_by_role('button', name='Approve', exact=True).bounding_box()['height'] >= 48
                    page.get_by_text('Connected. Your helpers are ready.', exact=True).wait_for(state='hidden', timeout=10000)
                    page.screenshot(path=str(OUT/f'home-{name}.png'), full_page=True)
                    (OUT/f'home-{name}.txt').write_text(home, encoding='utf-8')
                    page.get_by_role('button', name='Weekly release').click()
                    page.get_by_role('heading', name='4 · Publish').wait_for()
                    live = page.locator('.home-view').inner_text()
                    assert 'fixture-review' not in live
                    assert 'Repeats with Fix' in live
                    assert 'Stuck' in live
                    page.locator('details').first.locator('summary').click()
                    assert page.get_by_text('Job fixture-review', exact=True).is_visible()
                    page.locator('details').first.locator('summary').click()
                    assert page.locator('body').evaluate('(e) => e.scrollWidth <= window.innerWidth')
                    page.screenshot(path=str(OUT/f'live-{name}.png'), full_page=True)
                    (OUT/f'live-{name}.txt').write_text(live, encoding='utf-8')
                    assert not errors, errors
                    page.get_by_role('button', name='Back to Home', exact=True).click()
                    page.get_by_role('button', name='Approve', exact=True).click()
                    page.wait_for_function("window.BitCadenceStore.mode() === 'live'")
                    assert any(method == 'POST' and url.endswith('/api/jobs/fixture-gate/approve') for method,url in requests)
                    print(f'{name}: production Home -> live Score; progress, stalls, hidden ids, tap targets and read-only requests passed')
                finally:
                    context.close()
        finally:
            browser.close()
    assert all(method == 'GET' for method,url in requests if '/api/score/' in url), requests
    assert any('/api/score/autonomy/runs/fixture-run' in url for _, url in requests)


if __name__ == '__main__':
    main()
