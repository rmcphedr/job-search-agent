"""Single-attempt final submission with durable authorization and receipt evidence."""
from dataclasses import dataclass
from urllib.parse import urlsplit

from src.applications.browser_session import PageObservation, observe_page
from src.database.db import get_connection
from src.database.application_runs import _row, _now, transition_application
from src.database.application_automation import submission_readiness
from src.database.application_submissions import record_confirmed_application_submission


@dataclass(frozen=True)
class SubmissionOutcome:
    status: str
    submission: dict | None = None


ACKNOWLEDGMENTS = ('your application has been submitted', 'your application has been received',
                   'we have received your application', 'application successfully submitted')


def confirmation_messages(page) -> set[str]:
    """Only visible success statements in semantic confirmation elements qualify."""
    messages = page.evaluate("""() => [...document.querySelectorAll(
        '[role=status], [role=alert], h1, h2, [role=heading]'
    )].filter(el => el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden')
      .map(el => el.textContent.trim())""")
    normalized = {' '.join(text.casefold().split()).rstrip('.!') for text in messages}
    return normalized.intersection(ACKNOWLEDGMENTS)


def inspect_receipt(page, before: PageObservation, *, previous: set[str] | None = None) -> dict | None:
    """Require a new, explicit success statement in a visible confirmation element."""
    page.wait_for_load_state('domcontentloaded')
    for _ in range(20):
        current = observe_page(page)
        if urlsplit(current.url).netloc != urlsplit(before.url).netloc:
            return None
        new_messages = confirmation_messages(page) - (previous or set())
        if new_messages and not current.final_action and not current.gates and not current.validation:
            return {'url': current.url, 'acknowledgment': sorted(new_messages)[0],
                    'evidence': 'new_visible_confirmation_element'}
        page.wait_for_timeout(250)
    return None


def submit_if_authorized(run_id: int, page, observation: PageObservation, *, expected_owner: str) -> SubmissionOutcome:
    db = get_connection()
    try:
        db.execute('BEGIN IMMEDIATE')
        run = _row(db, run_id)
        if run['status'] == 'submitted':
            snapshot = record_confirmed_application_submission(run_id, {}, connection=db)
            db.commit()
            return SubmissionOutcome('submitted', snapshot)
        if run['submission_attempted_at']:
            if run['status'] not in {'cancelled','failed'}:
                transition_application(run_id, 'submission_uncertain', connection=db)
                db.commit()
            return SubmissionOutcome('submission_uncertain')
        if run['status'] != 'filling' or not expected_owner or run['lease_owner'] != expected_owner or (run['lease_expires_at'] or '') <= _now():
            return SubmissionOutcome(run['status'])
        if run['mode'] != 'fully_automate':
            transition_application(run_id, 'ready_for_review', connection=db)
            db.commit()
            return SubmissionOutcome('ready_for_review')
        current = observe_page(page)
        fields = submission_readiness(db, run['job_id'])
        saved = {f['field_key']:f for f in fields or []}
        valid = fields is not None and not current.gates and not current.validation and current.final_action and not current.next_action
        valid = valid and current.page_identity == observation.page_identity and current.url == observation.url
        valid = valid and all(not f.required or f.field_key in saved for f in current.fields)
        # Recheck live values; structural identity deliberately excludes entered data.
        if valid:
            for field in current.fields:
                stored = saved.get(field.field_key)
                if not stored or not stored['value']:
                    continue
                control = page.get_by_label(field.label, exact=True)
                if field.field_type == 'file':
                    from pathlib import Path
                    if field.field_key in dict(current.uploads):
                        valid = False  # Custom uploads require provider-specific verification.
                    else:
                        valid = control.evaluate('(el) => [...el.files].map(f => f.name)') == [Path(stored['value']).name]
                elif field.field_type == 'checkbox':
                    valid = control.is_checked() == (stored['value'].casefold() in {'yes','true'})
                elif field.field_type == 'select':
                    valid = control.locator('option:checked').inner_text().strip() == stored['value']
                else:
                    valid = control.input_value() == stored['value']
                if not valid:
                    break
        locator = page.get_by_role(current.final_action.role, name=current.final_action.name, exact=True) if valid else None
        if not valid or locator.count() != 1:
            transition_application(run_id, 'needs_user', pause_reason='Final submission readiness requires review', connection=db)
            db.commit()
            return SubmissionOutcome('needs_user')
        previous_confirmations = confirmation_messages(page)
        checkpoint = dict(run['checkpoint'])
        checkpoint['submission_snapshot'] = {'application_fields': fields, 'application_url':current.url}
        transition_application(run_id, 'submitting', checkpoint=checkpoint, expected_owner=expected_owner, connection=db)
        db.commit()  # Irreversible-action marker must be durable BEFORE click.
    finally:
        db.close()
    try:
        locator.click()
        receipt = inspect_receipt(page, current, previous=previous_confirmations)
        if receipt:
            snapshot = record_confirmed_application_submission(run_id, receipt)
            return SubmissionOutcome('submitted', snapshot)
    except Exception:
        # A click or receipt persistence failure cannot safely be retried.
        pass
    transition_application(run_id, 'submission_uncertain', pause_reason='Verify employer receipt before reconciliation')
    return SubmissionOutcome('submission_uncertain')
