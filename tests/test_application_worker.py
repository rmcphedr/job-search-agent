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
