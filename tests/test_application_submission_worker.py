from dataclasses import replace
from types import SimpleNamespace
import pytest
from tests.test_application_worker import env, observation
from src.database import application_runs as runs
from src.applications import submission as s

@pytest.fixture
def ready(env, monkeypatch):
    root, connect = env
    monkeypatch.setattr(s, 'get_connection', connect)
    monkeypatch.setattr('src.database.application_submissions.get_connection', connect)
    run = runs.enqueue_application(1, 'fully_automate')
    runs.claim_next_application('test', run_id=run['run_id'])
    runs.transition_application(run['run_id'], 'filling')
    with connect() as db:
        db.execute("INSERT INTO application_sessions(job_id,provider,application_url) VALUES(1,'generic_web_form','https://example.test/apply')")
    obs = observation()
    page = SimpleNamespace(url=obs.url, clicks=0)
    def click():
        assert runs.read_application_run(run['run_id'])['submission_attempted_at']
        page.clicks += 1
    page.get_by_role = lambda *a, **k: SimpleNamespace(count=lambda:1, click=click)
    monkeypatch.setattr(s, 'observe_page', lambda p: obs)
    monkeypatch.setattr(s, 'inspect_receipt', lambda p, before: {'url':p.url, 'acknowledgment':'Your application has been submitted.'})
    return run['run_id'], page, obs, connect

def test_confirmed_once_and_immutable(ready):
    run, page, obs, connect = ready
    result = s.submit_if_authorized(run,page,obs)
    assert result.status == 'submitted'
    assert s.submit_if_authorized(run,page,obs).submission == result.submission
    assert page.clicks == 1
    with connect() as db:
        assert db.execute('SELECT stage FROM tracked_jobs').fetchone()[0] == 'applied'

@pytest.mark.parametrize('problem', ['draft','missing','unapproved','gate','validation','changed','document'])
def test_blocked(ready, monkeypatch, problem):
    run,page,obs,connect = ready
    if problem == 'draft': runs.set_application_mode(run,'draft_for_review')
    if problem in {'missing','unapproved','document'}:
        with connect() as db:
            db.execute("INSERT INTO application_fields(job_id,section,field_key,label,field_type,required,value,status,disposition) VALUES(1,'questions','answer','Answer',?,1,?,?,'provided')", ('file' if problem=='document' else 'text', '' if problem=='missing' else '/missing', 'draft' if problem=='unapproved' else 'reviewed'))
    if problem in {'gate','validation','changed'}:
        changed = replace(obs, **({'gates':('captcha',)} if problem=='gate' else {'validation':('invalid',)} if problem=='validation' else {'page_identity':'new'}))
        monkeypatch.setattr(s,'observe_page',lambda p: changed)
    assert s.submit_if_authorized(run,page,obs).status == ('ready_for_review' if problem=='draft' else 'needs_user')
    assert page.clicks == 0

def test_ambiguous_never_retries(ready, monkeypatch):
    run,page,obs,connect = ready
    monkeypatch.setattr(s,'inspect_receipt',lambda *a: None)
    assert s.submit_if_authorized(run,page,obs).status == 'submission_uncertain'
    assert s.submit_if_authorized(run,page,obs).status == 'submission_uncertain'
    assert page.clicks == 1
    with connect() as db:
        assert db.execute('SELECT stage FROM tracked_jobs').fetchone()[0] == 'applying'
        assert db.execute('SELECT count(*) FROM application_submissions').fetchone()[0] == 0

def test_click_exception_is_uncertain(ready):
    run,page,obs,connect = ready
    def fail(): raise RuntimeError('connection interrupted')
    page.get_by_role = lambda *a, **k: SimpleNamespace(count=lambda:1, click=fail)
    assert s.submit_if_authorized(run,page,obs).status == 'submission_uncertain'
    assert runs.read_application_run(run)['submission_attempted_at']


def test_receipt_requires_explicit_acknowledgment(monkeypatch):
    obs = observation()
    page = SimpleNamespace(wait_for_load_state=lambda *a:None, wait_for_timeout=lambda *a:None)
    page.locator = lambda *a: SimpleNamespace(inner_text=lambda:'Thank you')
    monkeypatch.setattr(s,'observe_page',lambda p:replace(obs,final_action=None))
    assert s.inspect_receipt(page,obs) is None
    page.locator = lambda *a: SimpleNamespace(inner_text=lambda:'Your application has been submitted')
    assert s.inspect_receipt(page,obs)['acknowledgment']
    monkeypatch.setattr(s,'observe_page',lambda p:obs)
    assert s.inspect_receipt(page,obs) is None


def test_snapshot_failure_rolls_back_every_write(ready):
    from src.database.application_submissions import record_confirmed_application_submission
    run,page,obs,connect = ready
    runs.transition_application(run,'submitting',checkpoint={'submission_snapshot':{'application_url':obs.url,'application_fields':[]}})
    with connect() as db:
        db.execute("CREATE TRIGGER fail_history BEFORE INSERT ON application_stage_history BEGIN SELECT RAISE(ABORT,'test failure'); END")
    with pytest.raises(Exception, match='test failure'):
        record_confirmed_application_submission(run,{'url':obs.url,'acknowledgment':'received'})
    with connect() as db:
        assert db.execute('SELECT count(*) FROM application_submissions').fetchone()[0] == 0
        assert db.execute('SELECT stage FROM tracked_jobs').fetchone()[0] == 'applying'
        assert db.execute('SELECT status FROM application_runs').fetchone()[0] == 'submitting'

@pytest.mark.parametrize('live_value,expected', [('Approved answer','submitted'),('Changed answer','needs_user')])
def test_live_answer_must_match_approval(ready, monkeypatch, live_value, expected):
    from src.applications.dayforce import ApplicationField
    run,page,obs,connect = ready
    field = ApplicationField('questions','answer','Answer','text',True)
    obs = replace(obs,fields=(field,))
    monkeypatch.setattr(s,'observe_page',lambda p:obs)
    page.get_by_label = lambda *a, **k: SimpleNamespace(input_value=lambda:live_value)
    with connect() as db:
        db.execute("INSERT INTO application_fields(job_id,section,field_key,label,field_type,required,value,status,disposition) VALUES(1,'questions','answer','Answer','text',1,'Approved answer','reviewed','provided')")
    assert s.submit_if_authorized(run,page,obs).status == expected
    assert page.clicks == (expected == 'submitted')
