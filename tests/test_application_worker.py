from contextlib import contextmanager
from types import SimpleNamespace
import sqlite3
import pytest
from src.database.db import SCHEMA_FILE
from src.database import application_runs as runs

@pytest.fixture
def env(tmp_path, monkeypatch):
    path = tmp_path / 'test.db'
    def connect():
        db = sqlite3.connect(path); db.row_factory = sqlite3.Row
        return db
    with connect() as db:
        db.executescript(SCHEMA_FILE.read_text())
        db.execute("INSERT INTO companies(company_id,company_name,website) VALUES(1,'Example','https://example.test')")
        db.execute("INSERT INTO job_postings(job_id,company_id,title,url,description,description_status,description_source) VALUES(1,1,'Engineer','https://example.test/apply','Verified text','enriched','employer')")
    for module in ('application_runs','application_workspace','application_preparation','application_automation'):
        monkeypatch.setattr(f'src.database.{module}.get_connection', connect)
    return tmp_path, connect

def setup_worker(env, monkeypatch, pages, bridge=None):
    from src.orchestration import application_worker as w
    root, connect = env
    monkeypatch.setattr(w, 'get_connection', connect)
    monkeypatch.setattr(w, 'get_project_root', lambda: root)
    state = SimpleNamespace(index=0, closed=False, fills=[], generations=[])
    page = SimpleNamespace(url='about:blank', goto=lambda url: None)
    browser = SimpleNamespace(page=page, resume=lambda checkpoint: pages[state.index])
    @contextmanager
    def factory(run_id):
        try: yield browser
        finally: state.closed = True
    monkeypatch.setattr(w, 'fill_observed_page', lambda page, obs, values: (state.fills.append(values) or w.FillOutcome(tuple(values))))
    def advance(page, obs):
        state.index += 1
        return pages[state.index]
    monkeypatch.setattr(w, 'advance_nonfinal', advance)
    def generate(job, include_cover_letter=False):
        state.generations.append(include_cover_letter)
        doc = root / 'resume.docx'; doc.write_text('document')
        artifacts = {'resume_docx': str(doc)}
        if include_cover_letter: artifacts['cover_letter_docx'] = str(doc)
        return SimpleNamespace(status='complete', artifacts=artifacts)
    def answer(run_id, question, evidence):
        assert 'profile_files' in evidence and 'application_facts' in evidence
        return SimpleNamespace(answer='Draft response', approval_status='approval_required')
    run = runs.enqueue_application(1, 'draft_for_review')
    return w, state, run['run_id'], dict(browser_factory=factory, answer_agent=answer, resume_bridge=bridge or generate)

def observation(fields=(), *, next=False, gates=()):
    from src.applications.browser_session import PageObservation, PageAction
    return PageObservation('https://example.test/apply', str(fields)+str(gates), tuple(fields), (), tuple(gates), PageAction('Next') if next else None, None if next else PageAction('Submit'))

@pytest.mark.parametrize('change', ["active=0", "description_status='not_found'"])
def test_invalid_posting_pauses_before_browser(env, monkeypatch, change):
    w, state, run, deps = setup_worker(env, monkeypatch, [observation()])
    with env[1]() as db: db.execute('UPDATE job_postings SET '+change)
    assert w.process_application_run(run, **deps)['status'] == 'needs_user'
    assert not state.generations

@pytest.mark.parametrize('cover', [False, True])
def test_documents_once_and_review_packet(env, monkeypatch, cover):
    from src.applications.dayforce import ApplicationField
    fields = [ApplicationField('resume','resume','Resume','file',True)]
    if cover: fields.append(ApplicationField('cover_letter','cover_letter','Cover letter','file',True))
    w, state, run, deps = setup_worker(env, monkeypatch, [observation(fields)])
    assert w.process_application_run(run, **deps)['status'] == 'ready_for_review'
    packet = runs.get_review_packet(run)
    assert packet['artifacts']['resume_docx']
    assert state.generations == [cover]
    w.process_application_run(run, **deps)
    assert state.generations == [cover]

def test_later_question_pause_resume(env, monkeypatch):
    from src.applications.dayforce import ApplicationField
    from src.database.application_workspace import update_application_field
    question = ApplicationField('questions','why','Why','textarea',True)
    w, state, run, deps = setup_worker(env, monkeypatch, [observation(next=True), observation([question])])
    assert w.process_application_run(run, **deps)['status'] == 'needs_user'
    checkpoint = runs.get_review_packet(run)['run']['checkpoint']
    update_application_field(1, 'why', 'Approved response')
    runs.resume_application(run)
    assert runs.get_review_packet(run)['run']['checkpoint'] == checkpoint
    assert w.process_application_run(run, **deps)['status'] == 'ready_for_review'
    assert state.fills[-1]['why'] == 'Approved response'

def test_invalid_artifact_pauses(env, monkeypatch):
    from src.applications.dayforce import ApplicationField
    bridge = lambda *a, **kw: SimpleNamespace(status='complete', artifacts={'resume_docx':'/missing/file.docx'})
    w, state, run, deps = setup_worker(env, monkeypatch, [observation([ApplicationField('resume','resume','Resume','file',True)])], bridge)
    assert w.process_application_run(run, **deps)['status'] == 'needs_user'
    assert not state.fills

def test_watch_keeps_browser_until_resume(env, monkeypatch):
    from src.database.application_runs import resume_application
    w, state, run, deps = setup_worker(env, monkeypatch, [observation(gates=('account',)), observation()])
    def wake(seconds):
        if runs.read_application_run(run)['status'] == 'needs_user':
            assert not state.closed
            state.index = 1
            resume_application(run)
        else:
            raise KeyboardInterrupt
    monkeypatch.setattr(w.time, 'sleep', wake)
    with pytest.raises(KeyboardInterrupt):
        w.run_worker(watch=True, **deps)
    assert runs.read_application_run(run)['status'] == 'ready_for_review'
    assert state.closed


def test_uploaded_document_is_in_durable_packet(env, monkeypatch):
    from src.applications.dayforce import ApplicationField
    w, state, run, deps = setup_worker(env, monkeypatch, [observation([ApplicationField('resume','resume','Resume','file',True)])])
    w.process_application_run(run, **deps)
    field = runs.get_review_packet(run)['fields'][0]
    assert field['value'] == state.fills[0]['resume']

def test_later_cover_letter_does_not_regenerate_resume(env, monkeypatch):
    from src.applications.dayforce import ApplicationField
    resume = ApplicationField('resume','resume','Resume','file',True)
    cover = ApplicationField('cover_letter','cover_letter','Cover letter','file',True)
    w, state, run, deps = setup_worker(env, monkeypatch, [observation([resume], next=True), observation([cover])])
    calls = []
    def cover_only(job):
        calls.append(job['job_id'])
        path = env[0] / 'cover.docx'; path.write_text('letter')
        return SimpleNamespace(status='complete', artifacts={'cover_letter_docx': str(path)})
    deps['resume_bridge'].cover_letter = cover_only
    assert w.process_application_run(run, **deps)['status'] == 'ready_for_review'
    assert state.generations == [False]
    assert calls == [1]

@pytest.mark.parametrize('source', ['observation', 'outcome'])
def test_provider_validation_does_not_persist_candidate_value(env, monkeypatch, source):
    from dataclasses import replace
    secret = 'candidate.private@example.test'
    obs = observation()
    if source == 'observation':
        obs = replace(obs, validation=(f'Email {secret} is invalid',), gates=('account',))
    w, state, run, deps = setup_worker(env, monkeypatch, [obs])
    if source == 'outcome':
        monkeypatch.setattr(w, 'fill_observed_page', lambda *args: w.FillOutcome(validation=(f'Email {secret} is invalid',)))
    result = w.process_application_run(run, **deps)
    assert result['status'] == 'needs_user'
    assert result['checkpoint']['validation'] == ['provider_validation_error']
    with env[1]() as db:
        assert secret not in str([tuple(row) for row in db.execute('SELECT checkpoint_json FROM application_runs')])
        assert secret not in str([tuple(row) for row in db.execute('SELECT details_json FROM application_audit_events')])


def test_changed_question_invalidates_reviewed_answer(env, monkeypatch):
    from src.applications.dayforce import ApplicationField
    from src.database.application_workspace import update_application_field
    first = ApplicationField('questions', 'experience', 'Experience', 'select', True, ('One year', 'Two years'))
    second = ApplicationField('questions', 'experience', 'Experience', 'select', True, ('Two years', 'Three years'))
    w, state, run, deps = setup_worker(env, monkeypatch, [observation([first]), observation([second])])
    assert w.process_application_run(run, **deps)['status'] == 'needs_user'
    update_application_field(1, 'experience', 'Two years')
    runs.resume_application(run)
    state.index = 1
    assert w.process_application_run(run, **deps)['status'] == 'needs_user'
    assert not state.fills
    assert runs.get_review_packet(run)['fields'][0]['status'] != 'reviewed'


def test_watch_resume_reclaims_lease(env, monkeypatch):
    w, state, run, deps = setup_worker(env, monkeypatch, [observation(gates=('account',)), observation()])
    def wake(seconds):
        if runs.read_application_run(run)['status'] == 'needs_user':
            state.index = 1
            runs.resume_application(run)
        else:
            raise KeyboardInterrupt
    def fill(page, obs, values):
        current = runs.read_application_run(run)
        assert current['lease_owner']
        assert current['lease_expires_at']
        return w.FillOutcome()
    monkeypatch.setattr(w, 'fill_observed_page', fill)
    monkeypatch.setattr(w.time, 'sleep', wake)
    with pytest.raises(KeyboardInterrupt):
        w.run_worker(watch=True, **deps)
    assert runs.read_application_run(run)['status'] == 'ready_for_review'


def test_browser_lock_contention_releases_claim(env, monkeypatch):
    w, state, run, deps = setup_worker(env, monkeypatch, [observation()])
    @contextmanager
    def busy(run_id):
        raise w.BrowserPause('Another application run owns the browser')
        yield
    deps['browser_factory'] = busy
    w.run_worker(watch=False, **deps)
    current = runs.read_application_run(run)
    assert current['status'] == 'queued'
    assert current['lease_owner'] is None
    assert current['lease_expires_at'] is None


def test_watch_does_not_resume_when_competitor_claims(env, monkeypatch):
    w, state, run, deps = setup_worker(env, monkeypatch, [observation(gates=('account',)), observation()])
    def wake(seconds):
        if runs.read_application_run(run)['status'] == 'needs_user':
            runs.resume_application(run)
            assert runs.claim_next_application('competing-worker', run_id=run)
            state.index = 1
        else:
            raise KeyboardInterrupt
    monkeypatch.setattr(w.time, 'sleep', wake)
    with pytest.raises(KeyboardInterrupt):
        w.run_worker(watch=True, **deps)
    assert not state.fills
    assert state.closed
    assert runs.read_application_run(run)['lease_owner'] == 'competing-worker'


def test_lease_renewal_and_stale_owner_cannot_mutate(env, monkeypatch):
    w, state, run, deps = setup_worker(env, monkeypatch, [observation()])
    claimed = runs.claim_next_application('first-worker', run_id=run, lease_seconds=1)
    assert runs.renew_application_lease(run, 'first-worker', lease_seconds=900)
    assert runs.read_application_run(run)['lease_expires_at'] > claimed['lease_expires_at']
    with env[1]() as db:
        db.execute("UPDATE application_runs SET lease_expires_at='2000-01-01T00:00:00+00:00'")
    assert not runs.renew_application_lease(run, 'first-worker')
    assert runs.claim_next_application('second-worker', run_id=run)
    with pytest.raises(ValueError, match='changed'):
        runs.transition_application(run, 'filling', expected_owner='first-worker')
    runs.release_application_claim(run, 'first-worker')
    assert runs.read_application_run(run)['lease_owner'] == 'second-worker'


def test_heartbeat_renews_while_external_work_is_running(env, monkeypatch):
    import threading
    w, state, run, deps = setup_worker(env, monkeypatch, [observation()])
    owner = 'heartbeat-worker'
    claimed = runs.claim_next_application(owner, run_id=run, lease_seconds=1)
    real_event = threading.Event
    renewed = real_event()
    class FastFirstWait:
        def __init__(self):
            self.event = real_event()
            self.first = True
        def wait(self, seconds):
            if self.first:
                self.first = False
                return False
            renewed.set()
            return self.event.wait(seconds)
        def set(self): self.event.set()
    monkeypatch.setattr(w, 'threading', SimpleNamespace(Event=FastFirstWait, Thread=threading.Thread))
    with w._maintain_lease(run, owner):
        assert renewed.wait(2)
        assert runs.read_application_run(run)['lease_expires_at'] > claimed['lease_expires_at']
