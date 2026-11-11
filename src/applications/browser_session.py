"""Live application observations and non-final navigation in an isolated browser.

The caller owns authorization and durable run transitions. Keep this context open
while waiting for user handoff; resume always reads the current DOM. No operation
in this module clicks final submit or persists field values/passwords.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.applications.dayforce import ApplicationField, _key


class BrowserPause(RuntimeError):
    """The caller must request user help rather than guess a browser action."""


@dataclass(frozen=True)
class PageAction:
    name: str
    role: str = "button"


@dataclass(frozen=True)
class PageObservation:
    url: str
    page_identity: str
    fields: tuple[ApplicationField, ...]
    validation: tuple[str, ...]
    gates: tuple[str, ...]
    next_action: PageAction | None
    final_action: PageAction | None
    uploads: tuple[tuple[str, str], ...] = ()

    def checkpoint(self) -> dict[str, str]:
        """Only location and structural identity; never answers or browser state."""
        return {"url": self.url, "page_identity": self.page_identity}


@dataclass(frozen=True)
class FillOutcome:
    filled: tuple[str, ...] = ()
    unresolved: tuple[str, ...] = ()
    validation: tuple[str, ...] = ()


# Exact positive recognition only. An unfamiliar control requires handoff.
NEXT_NAMES = {"next", "continue", "save and continue", "next step"}
FINAL_NAMES = {"submit", "submit application", "send application", "apply", "apply now"}
UPLOAD_NAMES = {"resume", "upload resume", "cover letter", "upload cover letter", "additional documents", "upload additional documents"}


def observe_page(page: Any) -> PageObservation:
    """Inspect live visible controls, including provider upload buttons."""
    data = page.evaluate('''() => {
      const visible = el => !!(el.getClientRects().length) && getComputedStyle(el).visibility !== 'hidden';
      const label = el => el.getAttribute('aria-label') || (el.labels && [...el.labels].map(x=>x.textContent.trim()).join(' ')) || el.getAttribute('placeholder') || el.name || el.id || '';
      const forms = [...document.forms].filter(visible);
      const root = forms.length === 1 ? forms[0] : document.body;
      return {
        ambiguous: forms.length > 1,
        fields: [...root.querySelectorAll('input,textarea,select,[role=combobox]')].filter(el=>visible(el) || el.type==='file').filter(el=>!['hidden','submit','button','reset'].includes(el.type)).map(el=>({
          label:label(el), type:el.getAttribute('role') === 'combobox' && el.tagName !== 'SELECT' ? 'combobox' : (el.type || el.tagName.toLowerCase()), required:el.required || el.getAttribute('aria-required')==='true',
          options:el.options ? [...el.options].filter(x=>x.value).map(x=>x.textContent.trim()) : []})),
        actions:[...root.querySelectorAll('button,input[type=submit],input[type=button],[role=button],a')].filter(visible).filter(el=>!el.disabled).map(el=>({name:el.getAttribute('aria-label') || el.textContent.trim() || el.value || '',role:el.tagName==='A'?'link':'button'})),
        errors:[...document.querySelectorAll('[role=alert],.field-validation-error,.validation-summary-errors,[aria-invalid=true]')].filter(visible).map(el=>el.validationMessage || el.textContent.trim() || 'Invalid field'),
        captcha:[...document.querySelectorAll('iframe[src*=recaptcha],iframe[src*=hcaptcha],.g-recaptcha,.h-captcha')].some(visible),
        text:document.body.innerText
      };
    }''')
    fields = []
    gates = ["unsupported_control"] if data["ambiguous"] else []
    seen = set()
    for item in data["fields"]:
        label = item["label"].strip()
        kind = item["type"]
        if kind == "password":
            gates.append("account")
            continue
        if not label or kind in {"radio", "select-multiple", "combobox"}:
            gates.append("unsupported_control")
            continue
        key = _key(label)
        section = "questions"
        if kind == "file":
            key = "cover_letter" if "cover" in key else "additional_documents" if "additional" in key else "resume"
            section = key
        if key in seen:
            gates.append("unsupported_control")
            continue
        seen.add(key)
        fields.append(ApplicationField(section, key, label, "select" if kind == "select-one" else kind,
                                       item["required"], tuple(item["options"]), len(fields)+1))
        if kind == "checkbox" and any(word in label.casefold() for word in ("agree", "consent", "privacy", "certify", "accept", "terms", "conditions")):
            # Consent is direct user action, even when a value was supplied.
            if not page.get_by_label(label, exact=True).is_checked():
                gates.append("consent")
    text = data["text"].casefold()
    if any(word in text for word in ("verify your email", "verification code", "two-factor", "multi-factor")):
        gates.append("verification")
    if data["captcha"]:
        gates.append("captcha")
    next_actions, final_actions, uploads = [], [], []
    for action in data["actions"]:
        name = action["name"].strip()
        normalized = name.casefold()
        if normalized in NEXT_NAMES:
            next_actions.append(PageAction(name, action["role"]))
        elif normalized in FINAL_NAMES:
            final_actions.append(PageAction(name, action["role"]))
        elif normalized in UPLOAD_NAMES:
            key = "cover_letter" if "cover" in normalized else "additional_documents" if "additional" in normalized else "resume"
            if key not in seen:
                fields.append(ApplicationField(key, key, name, "file", position=len(fields)+1))
                seen.add(key)
                uploads.append((key, name))
        elif normalized in {"sign in", "log in", "create account", "register"}:
            gates.append("account")
    if len(next_actions) > 1 or len(final_actions) > 1:
        gates.append("unsupported_control")
    structure = [page.url, [(f.field_key, f.field_type, f.required, f.options) for f in fields], data["actions"]]
    identity = hashlib.sha256(json.dumps(structure, sort_keys=True).encode()).hexdigest()
    return PageObservation(page.url, identity, tuple(fields), tuple(data["errors"]), tuple(sorted(set(gates))),
                           next_actions[0] if len(next_actions)==1 else None,
                           final_actions[0] if len(final_actions)==1 else None, tuple(uploads))


def live_control_is_empty(page: Any, field, observation: PageObservation) -> bool:
    """Omitted answers must not transmit browser-prefilled or user-added data."""
    if field.field_key in dict(observation.uploads):
        return False  # Custom uploads cannot be verified generically.
    control = page.get_by_label(field.label, exact=True)
    try:
        if field.field_type == 'file':
            return control.evaluate('(el) => el.files.length') == 0
        if field.field_type == 'checkbox':
            return not control.is_checked()
        return control.input_value() == ''
    except Exception:
        return False


def fill_observed_page(page: Any, observation: PageObservation, values: dict[str, str]) -> FillOutcome:
    current = observe_page(page)
    if current.page_identity != observation.page_identity:
        raise BrowserPause("Page changed; observe and resolve its fields again")
    if current.gates:
        return FillOutcome(unresolved=current.gates, validation=current.validation)
    filled, unresolved = [], []
    uploads = dict(current.uploads)
    for field in current.fields:
        if field.field_key not in values:
            if field.required or not live_control_is_empty(page, field, current):
                unresolved.append(field.field_key)
            continue
        value = values[field.field_key]
        try:
            control = page.get_by_label(field.label, exact=True)
            if field.field_type == "file":
                document = Path(value).expanduser()
                if not document.is_file():
                    unresolved.append(field.field_key)
                    continue
                if field.field_key in uploads:
                    with page.expect_file_chooser(timeout=5000) as chooser:
                        page.get_by_role("button", name=uploads[field.field_key], exact=True).click()
                    chooser.value.set_files(str(document.resolve()))
                else:
                    control.set_input_files(str(document.resolve()))
            elif field.field_type == "select":
                control.select_option(label=value)
            elif field.field_type == "checkbox":
                if value.casefold() not in {"true", "false", "yes", "no"}:
                    unresolved.append(field.field_key)
                    continue
                control.set_checked(value.casefold() in {"true", "yes"})
            else:
                control.fill(value)
                if control.input_value() != value:
                    unresolved.append(field.field_key)
                    continue
            filled.append(field.field_key)
        except Exception:
            # Do not persist exception strings that may contain sensitive values.
            unresolved.append(field.field_key)
    return FillOutcome(tuple(filled), tuple(unresolved), observe_page(page).validation)


def advance_nonfinal(page: Any, observation: PageObservation, *, values: dict[str, str] | None = None) -> PageObservation:
    current = observe_page(page)
    if current.page_identity != observation.page_identity:
        raise BrowserPause("Page changed; inspect before navigation")
    if current.gates or current.validation or not current.next_action or current.final_action:
        raise BrowserPause("Navigation requires user review")
    if values is not None and any(
        field.field_key not in values and not live_control_is_empty(page, field, current)
        for field in current.fields
    ):
        raise BrowserPause("Omitted field contains a value requiring approval")
    action = current.next_action
    locator = page.get_by_role(action.role, name=action.name, exact=True)
    if locator.count() != 1:
        raise BrowserPause("Navigation control is ambiguous")
    locator.click()
    page.wait_for_load_state("domcontentloaded")
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = observe_page(page)
        if result.page_identity != current.page_identity or result.validation or result.gates:
            return result
        page.wait_for_timeout(100)
    raise BrowserPause("Next did not reveal a changed page; inspect before retrying")


def reconcile_page(page: Any, checkpoint: dict[str, Any] | None = None) -> PageObservation:
    """Never restore old DOM assumptions, nor automatically replay final actions."""
    return observe_page(page)


@dataclass
class ApplicationBrowser:
    context: Any
    page: Any
    needs_replay: bool = False

    def resume(self, checkpoint: dict[str, Any] | None = None) -> PageObservation:
        observation = reconcile_page(self.page, checkpoint)
        self.needs_replay = bool(checkpoint and checkpoint.get("page_identity") != observation.page_identity)
        return observation


@contextmanager
def open_application_browser(run_id: int, *, profile_dir: Path | None = None, headless: bool = False):
    """Hold one process lock across the entire run, including user handoff.

    Profile isolation is per run to avoid sharing employer sessions across jobs.
    A global lock permits only one active application browser. Closing/reopening
    retains cookies, but callers must reconcile potentially lost wizard state.
    """
    from playwright.sync_api import sync_playwright

    if run_id <= 0:
        raise ValueError("A positive run ID is required")
    root = Path(profile_dir) if profile_dir else Path(__file__).resolve().parents[2] / "data/cache/application_browser"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    with (root / "owner.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise BrowserPause("Another application run owns the browser") from exc
        try:
            profile = root / f"run-{run_id}"
            profile.mkdir(mode=0o700, exist_ok=True)
            with sync_playwright() as playwright:
                context = playwright.chromium.launch_persistent_context(str(profile), headless=headless)
                try:
                    page = context.pages[0] if context.pages else context.new_page()
                    yield ApplicationBrowser(context, page)
                finally:
                    context.close()
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
