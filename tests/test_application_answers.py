"""Evidence and approval boundary for application answers."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from src.applications.answer_agent import draft_answer
from src.applications.answer_policy import classify_answer
from src.database.application_runs import approve_answer, enqueue_application
from src.database.db import SCHEMA_FILE


@pytest.fixture
def context(tmp_path, monkeypatch):
    db_path = tmp_path / 'test.db'
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA_FILE.read_text())
    connection.execute("INSERT INTO companies (company_id, company_name, website) VALUES (1,'Example','https://example.test')")
    connection.execute("INSERT INTO job_postings (job_id, company_id, title, active, description_status) VALUES (10,1,'Engineer',1,'enriched')")
    connection.execute("INSERT INTO application_fields (job_id,section,field_key,label) VALUES (10,'questions','unknown','Unknown question')")
    connection.commit()
    connection.close()
    def connect():
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        return db
    monkeypatch.setattr('src.database.application_runs.get_connection', connect)
    monkeypatch.setattr('src.applications.answer_agent.get_project_root', lambda: tmp_path)
    return tmp_path, connect


def _hermes(tmp_path: Path, payload: dict | str) -> Path:
    script = tmp_path / 'fake-hermes'
    output = payload if isinstance(payload, str) else json.dumps(payload)
    script.write_text('#!/usr/bin/env python3\nimport sys\nfrom pathlib import Path\nprompt=sys.argv[2]\npath=Path(prompt.split("OUTPUT_PATH: ",1)[1].splitlines()[0])\npath.parent.mkdir(parents=True,exist_ok=True)\npath.write_text(' + repr(output) + ')\n')
    script.chmod(0o755)
    return script


def test_confirmed_profile_and_explicit_fact_with_generated_resume_excluded(monkeypatch):
    monkeypatch.setattr('src.applications.answer_policy.sync_status', lambda root: (True, 'current'))
    evidence = {'profile_files': {'user/master_cv.md': '- **Email:** a@example.test\n- **Employer:** Acme'},
                'application_facts': {'work_authorization': {'value': 'Yes', 'source': 'user_confirmed'}},
                'generated_resume': 'Authorized to work anywhere'}
    assert classify_answer({'field_key': 'email', 'answer': 'a@example.test'}, evidence) == 'confirmed'
    assert classify_answer({'field_key': 'employer', 'answer': 'Acme'}, evidence) == 'confirmed'
    assert classify_answer({'field_key': 'work_authorization', 'answer': 'Yes'}, evidence) == 'confirmed'
    assert classify_answer({'field_key': 'work_authorization', 'answer': 'Authorized to work anywhere'}, evidence) == 'human_required'


def test_stale_master_profile_and_sensitive_fields(monkeypatch):
    monkeypatch.setattr('src.applications.answer_policy.sync_status', lambda root: (False, 'stale'))
    evidence = {'profile_files': {'user/master_cv.md': 'Email: a@example.test'}}
    assert classify_answer({'field_key': 'email', 'answer': 'a@example.test'}, evidence) == 'approval_required'
    for key in ('work_authorization', 'salary_expectation', 'demographic_disclosure', 'legal_attestation', 'privacy_consent'):
        assert classify_answer({'field_key': key, 'answer': 'Yes'}, evidence) == 'human_required'


def test_agent_draft_is_staged_and_cannot_fill_unknown_until_approved(context, monkeypatch):
    root, connect = context
    run = enqueue_application(10, 'fully_automate')
    payload = {'field_key': 'unknown', 'answer': 'I would use Python.', 'evidence_refs': ['user/project_inventory.md'], 'approval_status': 'approval_required'}
    monkeypatch.setenv('HERMES_EXECUTABLE', str(_hermes(root, payload)))
    draft = draft_answer(run['run_id'], {'field_key': 'unknown', 'label': 'Unknown question'}, {'profile_files': {'user/project_inventory.md': 'Python project'}})
    assert draft.approval_status == 'approval_required'
    assert (root / 'data/staging/application_runs' / str(run['run_id']) / 'answer_unknown.json').exists()
    with connect() as db:
        assert db.execute("SELECT value FROM application_fields WHERE field_key='unknown'").fetchone()[0] is None
    approved = approve_answer(run['run_id'], 'unknown', 'I would use Python.')
    assert approved['value'] == 'I would use Python.'
    with connect() as db:
        assert db.execute("SELECT value, disposition FROM application_fields WHERE field_key='unknown'").fetchone()[:] == ('I would use Python.', 'provided')


def test_invalid_agent_json_does_not_write_sqlite(context, monkeypatch):
    root, connect = context
    run = enqueue_application(10, 'fully_automate')
    monkeypatch.setenv('HERMES_EXECUTABLE', str(_hermes(root, '{invalid')))
    with pytest.raises(ValueError):
        draft_answer(run['run_id'], {'field_key': 'unknown'}, {})
    with connect() as db:
        assert db.execute("SELECT value FROM application_fields WHERE field_key='unknown'").fetchone()[0] is None


def test_unrelated_profile_text_cannot_confirm_answer(monkeypatch):
    monkeypatch.setattr('src.applications.answer_policy.sync_status', lambda root: (True, 'current'))
    evidence = {'profile_files': {'user/master_cv.md': '- **Employer:** Acme\n- **Email:** a@example.test'}}
    assert classify_answer({'field_key': 'email', 'answer': 'Acme'}, evidence) == 'approval_required'
    assert classify_answer({'field_key': 'email', 'answer': 'a@example.test'}, evidence) == 'confirmed'


def test_missing_master_profile_requires_approval(monkeypatch):
    monkeypatch.setattr('src.applications.answer_policy.sync_status', lambda root: (False, 'missing'))
    assert classify_answer({'field_key': 'email', 'answer': 'a@example.test'},
                           {'profile_files': {'user/master_cv.md': '- **Email:** a@example.test'}}) == 'approval_required'


@pytest.mark.parametrize(('source', 'answer', 'expected'), [
    ('- **Employer:** Not Acme', 'Acme', 'approval_required'),
    ('- **Email:** alice@example.com', 'example.com', 'approval_required'),
    ('- **Email:** alice-smith@example.com', 'alicesmith@example.com', 'approval_required'),
    ('- **Email:** alice-smith@example.com', 'alice-smith@example.com', 'confirmed'),
    ('- **Employer:** Not Acme', 'Not Acme', 'confirmed'),
])
def test_profile_fact_requires_exact_value(monkeypatch, source, answer, expected):
    monkeypatch.setattr('src.applications.answer_policy.sync_status', lambda root: (True, 'current'))
    key = 'email' if 'Email:' in source else 'employer'
    evidence = {'profile_files': {'user/master_cv.md': source}}
    assert classify_answer({'field_key': key, 'answer': answer}, evidence) == expected
