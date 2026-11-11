"""Bounded local application preparation; final submission is delegated separately."""
from __future__ import annotations

import argparse
import time
import threading
import uuid
from contextlib import nullcontext, contextmanager
from dataclasses import asdict
from pathlib import Path

from src.applications.answer_agent import draft_answer
from src.applications.answer_policy import PROFILE_FILES, classify_answer, valid_profile_sources
from src.applications.browser_session import (
    BrowserPause, FillOutcome, advance_nonfinal, fill_observed_page, open_application_browser,
)
from src.applications.dayforce import ApplicationInspection
from src.database.application_automation import list_application_facts, record_application_event, set_field_observation
from src.database.application_preparation import update_application_step
from src.database.application_runs import (claim_next_application, read_application_run, transition_application,
                                           renew_application_lease, release_application_claim)
from src.database.application_workspace import get_application_workspace, save_inspection, update_application_field
from src.database.db import get_connection, get_project_root
from src.integrations.resume_pipeline import run_resume_generation, run_cover_letter_generation


class DocumentBridge:
    """Generate once, adding later cover letters without rebuilding the resume."""

    def __call__(self, job, *, include_cover_letter=False):
        return run_resume_generation(job, include_cover_letter=include_cover_letter)

    def cover_letter(self, job):
        return run_cover_letter_generation(job)


def _evidence(job):
    root = get_project_root()
    profiles = {name: (root / name).read_text(encoding='utf-8') for name in PROFILE_FILES if (root / name).is_file()}
    return {'profile_files': valid_profile_sources({'profile_files': profiles}, root),
            'application_facts': {f['fact_key']: f for f in list_application_facts() if f['source'] == 'user_confirmed'},
            'job_evidence': {'title': job['title'], 'description': job['description'], 'url': job['url']}}


def final_page_ready(run_id, browser, observation, *, expected_owner):
    """Apply the current run mode at the final action boundary."""
    if read_application_run(run_id)["mode"] == "draft_for_review":
        return transition_application(run_id, "ready_for_review", expected_owner=expected_owner)
    from src.applications.submission import submit_if_authorized
    submit_if_authorized(run_id, browser.page, observation, expected_owner=expected_owner)
    return read_application_run(run_id)


@contextmanager
def _maintain_lease(run_id, worker_id):
    """Renew during slow external calls; every action also checks ownership."""
    stop = threading.Event()
    def heartbeat():
        while not stop.wait(30):
            try:
                renew_application_lease(run_id, worker_id)
            except Exception:
                # The next durable transition must still prove a live lease.
                return
    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join()


def process_application_run(run_id: int, *, browser_factory, answer_agent, resume_bridge) -> dict:
    owner = 'application-' + uuid.uuid4().hex
    claimed = claim_next_application(owner, run_id=run_id)
    if claimed is None:
        return read_application_run(run_id)
    with _maintain_lease(run_id, owner):
        try:
            return _process_application_run(run_id, worker_id=owner, browser_factory=browser_factory,
                                            answer_agent=answer_agent, resume_bridge=resume_bridge)
        finally:
            release_application_claim(run_id, owner)


def _process_application_run(run_id: int, *, worker_id, browser_factory, answer_agent, resume_bridge) -> dict:
    run = read_application_run(run_id)
    if run['status'] not in {'queued', 'inspecting', 'preparing', 'filling'}:
        return run
    checkpoint = dict(run['checkpoint'])
    def transition(status, reason=None):
        return transition_application(run_id, status, pause_reason=reason, checkpoint=checkpoint, expected_owner=worker_id)
    db = get_connection()
    try:
        job = dict(db.execute('SELECT j.*, c.company_name FROM job_postings j JOIN companies c USING(company_id) WHERE job_id=?', (run['job_id'],)).fetchone())
    finally:
        db.close()
    if not job['active'] or job['description_status'] != 'enriched' or not job['description_source'] or not str(job['description'] or '').strip():
        return transition('needs_user', 'Posting needs active, source-backed description verification')
    if run['submission_attempted_at']:
        return transition('submission_uncertain', 'Inspect the previous submission before continuing')
    try:
        transition('inspecting')
        evidence = _evidence(job)
        with browser_factory(run_id) as browser:
            if browser.page.url == 'about:blank':
                browser.page.goto(job['url'])
            observation = browser.resume(checkpoint)
            for _ in range(25):
                checkpoint.update(observation.checkpoint())
                pages = checkpoint.setdefault('pages', [])
                if observation.page_identity not in pages:
                    pages.append(observation.page_identity)
                checkpoint['validation'] = ['provider_validation_error'] if observation.validation else []
                transition('inspecting')
                save_inspection(job['job_id'], ApplicationInspection(
                    'generic_web_form', observation.url, observation.page_identity, observation.fields,
                    'account' in observation.gates, 'consent' in observation.gates, 'captcha' in observation.gates,
                ), preserve_fields=True)
                if observation.gates:
                    return transition('needs_user', ', '.join(observation.gates))
                artifacts = checkpoint.setdefault('artifacts', {})
                document_keys = {f.field_key for f in observation.fields if f.field_type == 'file'}
                needed = document_keys & {'resume', 'cover_letter'}
                if any(key + '_docx' not in artifacts for key in needed):
                    if checkpoint.get('document_generation_pending'):
                        return transition('needs_user', 'Reconcile interrupted document generation before retrying')
                    checkpoint['document_generation_pending'] = True
                    transition('preparing')
                    if 'resume_docx' in artifacts:
                        cover_only = getattr(resume_bridge, 'cover_letter', None)
                        if cover_only is None:
                            return transition('needs_user', 'Cover-letter-only bridge is required')
                        result = cover_only(job)
                    else:
                        result = resume_bridge(job, include_cover_letter='cover_letter' in needed)
                    if result.status != 'complete':
                        return transition('needs_user', 'Document generation needs review')
                    for key in needed:
                        path = Path(str(result.artifacts.get(key + '_docx') or ''))
                        if not path.is_absolute() or not path.is_file():
                            return transition('needs_user', 'Generated document path is unavailable')
                    artifacts.update(result.artifacts)
                    checkpoint.pop('document_generation_pending', None)
                    transition('preparing')
                    for key in needed:
                        update_application_step(job['job_id'], key, status='complete', details=f"{key}: {artifacts[key + '_docx']}")
                _, stored_fields = get_application_workspace(job['job_id'])
                stored = {f['field_key']: f for f in stored_fields}
                values = {}
                for field in observation.fields:
                    key = field.field_key
                    saved = stored[key]
                    if field.field_type == 'file':
                        value = artifacts.get(key + '_docx') or saved.get('value')
                        if value and Path(value).is_absolute() and Path(value).is_file():
                            values[key] = str(value)
                            update_application_field(job['job_id'], key, str(value))
                        elif field.required:
                            return transition('needs_user', f'Document required: {key}')
                        continue
                    if saved['status'] == 'reviewed' and saved.get('value'):
                        values[key] = saved['value']
                        continue
                    if saved['disposition'] in {'skipped', 'not_applicable'} and not field.required:
                        continue
                    fact = evidence['application_facts'].get(key, {})
                    value = fact.get('value', '')
                    question = asdict(field)
                    if not value:
                        transition('preparing')
                        draft = answer_agent(run_id, question, evidence)
                        value = draft.answer
                    policy = classify_answer({**question, 'answer': value}, evidence)
                    if policy != 'confirmed':
                        set_field_observation(job['job_id'], key, disposition='human_required')
                        return transition('needs_user', f'Answer approval required: {key}')
                    update_application_field(job['job_id'], key, value)
                    values[key] = value
                transition('filling')
                outcome = fill_observed_page(browser.page, observation, values)
                for key in outcome.filled:
                    set_field_observation(job['job_id'], key, disposition='provided')
                    record_application_event('field_filled', job_id=job['job_id'], target_key=key)
                checkpoint['validation'] = ['provider_validation_error'] if outcome.validation else []
                if outcome.unresolved or outcome.validation:
                    return transition('needs_user', 'Resolve field or provider validation errors')
                if observation.final_action:
                    transition('filling')
                    return final_page_ready(run_id, browser, observation, expected_owner=worker_id)
                if not observation.next_action:
                    return transition('needs_user', 'No recognized next or final control')
                transition('filling')
                observation = advance_nonfinal(browser.page, observation)
            return transition('needs_user', 'Page limit reached')
    except (BrowserPause, OSError, RuntimeError, ValueError) as exc:
        current = read_application_run(run_id)
        if current['status'] in {'cancelled', 'submitted', 'failed'} or current['lease_owner'] != worker_id:
            return current
        if not renew_application_lease(run_id, worker_id):
            return current
        # Exception text can contain candidate values; retain only the type.
        return transition('needs_user', f'Worker action requires review ({type(exc).__name__})')


def run_worker(*, watch=False, browser_factory=open_application_browser,
               answer_agent=draft_answer, resume_bridge=DocumentBridge(), poll_seconds=2):
    """Keep the context (and its process lock) alive while a user handles a gate."""
    owner = 'local-application-' + uuid.uuid4().hex
    while True:
        run = claim_next_application(owner)
        if run:
            run_id = run['run_id']
            try:
                with _maintain_lease(run_id, owner), browser_factory(run_id) as browser:
                    while True:
                        result = _process_application_run(run_id, worker_id=owner,
                            browser_factory=lambda _: nullcontext(browser),
                            answer_agent=answer_agent, resume_bridge=resume_bridge)
                        if not watch or result['status'] != 'needs_user':
                            break
                        while read_application_run(run_id)['status'] == 'needs_user':
                            time.sleep(poll_seconds)
                        # Pausing released the lease. Resume must win a new atomic claim.
                        if claim_next_application(owner, run_id=run_id) is None:
                            break
            except BrowserPause:
                # A retained handoff browser can own the global lock. Retry later.
                pass
            finally:
                release_application_claim(run_id, owner)
        if not watch:
            return
        time.sleep(poll_seconds)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--once', action='store_true')
    group.add_argument('--watch', action='store_true')
    args = parser.parse_args()
    run_worker(watch=args.watch)


if __name__ == '__main__':
    main()
