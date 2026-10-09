"""Execute the shipped Home projection and exercise the authenticated live read."""
import json
from pathlib import Path
import sqlite3
import subprocess
import os

import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from mco.orchestrator.auth import require_scopes
from mco.orchestrator.score_gate_routes import score_autonomy_router

ROOT = Path(__file__).parents[1]
VIEWS = ROOT / 'src/mco/console_src/43b328d0-9d0e-4fce-a105-be0a939d7e48.js'


def project(expression):
    source = VIEWS.read_text(encoding='utf-8')
    helpers = source[source.index('const HOME_STALL_MINUTES'):source.index('// ----- Overview -----')]
    result = subprocess.run(['node', '-e', helpers + '\nconsole.log(JSON.stringify(' + expression + '));'], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_stall_clock_uses_newest_sign_of_life_and_only_active_jobs():
    assert project("homeState({status:'in_progress',started_at:'2026-01-01T00:00:00Z'},[],Date.parse('2026-01-01T00:10:00Z'))") == 'Stuck'
    assert project("homeState({status:'in_progress',leased_by_instance_id:'a',started_at:'2026-01-01T00:00:00Z'},[{instance_id:'a',last_seen_at:'2026-01-01T00:09:00Z'}],Date.parse('2026-01-01T00:10:00Z'))") == 'Working'
    assert project("homeState({status:'pending',created_at:'2026-01-01T00:00:00Z'},[],Date.parse('2026-01-01T00:10:00Z'))") == 'Waiting'
    assert project("homeState({status:'completed'},[],Date.now())") == 'Done'
    assert project("homeState({status:'in_progress'},[],Date.now())") == 'Working'
    assert project("homeState({status:'in_progress',started_at:'2026-01-01T00:00:00Z',output_payload:{progress:{at:'2026-01-01T00:09:00Z'}}},[],Date.parse('2026-01-01T00:10:00Z'))") == 'Working'
    assert project("homeState({status:'needs_approval'},[],Date.now())") == 'Needs you'
    assert project("homeState({status:'cancelled'},[],Date.now())") == 'Stopped'


def test_progress_is_plain_and_sensitive_or_structured_text_is_not_shown():
    assert project("homeLine({status:'in_progress',output_payload:{progress:'Reading the install page.'}},[])") == 'Reading the install page.'
    assert project("homeLine({status:'in_progress',output_payload:{progress:{message:'Checking the changes.'}}},[])") == 'Checking the changes.'
    assert 'mco_tok_' not in project("homeLine({status:'in_progress',output_payload:{progress:'mco_tok_private'}},[])")
    assert '{' not in project("homeLine({status:'pending',output_payload:{progress:'{\"secret\":1}'}},[])")


def test_home_prioritizes_attention_and_keeps_distinct_runs():
    result = project("homeGroups([{id:'done',status:'completed'},{id:'gate',status:'needs_approval'},{id:'bad',status:'failed'},{id:'a',status:'pending',input_payload:{score:{run_id:'one'}}},{id:'b',status:'pending',input_payload:{score:{run_id:'two'}}}],[],Date.now())")
    assert [j['id'] for j in result['attention']] == ['gate', 'bad']
    assert [g['runId'] for g in result['running']] == ['one', 'two']


def test_live_stages_include_undispatched_tasks_and_explicit_review_loops():
    result = project("liveStages({tasks:[{id:'build',title:'Build',on_reject:'fix'},{id:'fix',title:'Fix'}],dispatch:[{task:'build',phase:'review',job_id:'j',status:'rejected'}]},[{id:'j',status:'completed',input_payload:{score:{attempt:2}}}])")
    assert [s['title'] for s in result] == ['Build', 'Fix']
    assert result[0]['loop'] == 'Repeats with Fix if changes are needed'
    assert result[0]['cards'][0]['round'] == 2
    assert result[0]['cards'][0]['job']['status'] == 'rejected'
    assert result[1]['cards'] == []


def test_production_shell_opens_live_score_and_bounded_adapter():
    shell = (ROOT / 'src/mco/console_src/8ec84a72-7b37-434d-a68b-2ac1188e3e6d.js').read_text(encoding='utf-8')
    source = VIEWS.read_text(encoding='utf-8')
    adapter = (ROOT / 'src/mco/console_src/47e66145-9c4d-41a1-acbb-42b12848f160.js').read_text(encoding='utf-8')
    assert 'overview: <Home' in shell
    assert 'scoreLive: <ScoreLive' in shell
    assert 'onWatch=' in shell and 'getScoreRun(runId)' in source
    assert 'api("/api/jobs?limit=200")' in adapter
    assert 'api("/api/jobs")' not in adapter
    assert '/api/score/autonomy/runs/' in adapter
    assert source.index('What needs you') < source.index("What's running")


def test_live_read_is_org_scoped_read_only_and_includes_plan(monkeypatch, tmp_path):
    import mco.config
    import mco.orchestrator.routes as board_routes
    from mco.localstore import LocalStore
    db = tmp_path / 'score.db'
    with sqlite3.connect(db) as conn:
        conn.executescript('CREATE TABLE runs(id TEXT,org TEXT,definition TEXT,status TEXT); CREATE TABLE dispatch(run TEXT,task TEXT,phase TEXT,job_id TEXT,status TEXT);')
        conn.execute('INSERT INTO runs VALUES(?,?,?,?)', ('run', 'ours', json.dumps({'id':'score','tasks':[{'id':'future','title':'Future'}]}), 'running'))
        conn.execute('INSERT INTO dispatch VALUES(?,?,?,?,?)', ('run','future','work','job','dispatched'))
    board = LocalStore(tmp_path / 'board.db')
    board.table('agent_jobs').insert({'id':'job','org_id':'ours','title':'Future','status':'in_progress',
        'input_payload':{'prompt':'private instructions','score':{'attempt':2}},
        'output_payload':{'result':'private evidence','progress':'Checking the changes.'}}).execute()
    monkeypatch.setattr(board_routes,'get_db_client',lambda:board)
    monkeypatch.setattr(mco.config, 'get_config', lambda: {'MCO_SCORE_DB': str(db)})
    from mco.orchestrator import score_sweep
    monkeypatch.setattr(score_sweep, 'get_database', lambda config: db)
    app = FastAPI()
    app.include_router(score_autonomy_router)
    # Override the shared auth dependency (newer FastAPI hides per-route dependencies).
    from mco.orchestrator.auth import require_agent as dep
    assert TestClient(app).get('/api/score/autonomy/runs/run').status_code == 401
    app.dependency_overrides[dep] = lambda: {'org_id':'ours','scopes':['jobs:read']}
    before = db.read_bytes()
    http = TestClient(app)
    response = http.get('/api/score/autonomy/runs/run')
    assert response.status_code == 200
    assert response.json()['tasks'][0]['title'] == 'Future'
    assert response.json()['jobs'][0]['output_payload'] == {'progress':'Checking the changes.'}
    assert response.json()['jobs'][0]['input_payload'] == {'score':{'attempt':2}}
    assert 'private' not in response.text
    assert db.read_bytes() == before
    app.dependency_overrides[dep] = lambda: {'org_id':'other'}
    assert http.get('/api/score/autonomy/runs/run').status_code == 404
    assert http.get('/api/score/autonomy/runs/missing').status_code == 404


@pytest.mark.skipif(os.environ.get('BC_TEST_BROWSER') != '1', reason='Set BC_TEST_BROWSER=1 with Playwright Chromium installed')
def test_shipped_bundle_home_opens_read_only_live_run():
    """Exercise real React click handlers and fetches, beyond source assertions."""
    import sys
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/capture_home_live.py')],
                            cwd=ROOT, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'production Home -> live Score' in result.stdout
