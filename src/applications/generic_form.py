"""Generic single-page application form discovery and reviewed browser filling."""

from __future__ import annotations

from pathlib import Path

from bs4 import BeautifulSoup, Tag

from src.applications.dayforce import ApplicationField, ApplicationInspection, _clean_label, _key
from src.jobs.board_discovery.playwright_client import PlaywrightBrowserClient


def _label(control: Tag, form: Tag) -> str:
    label = str(control.get("aria-label") or control.get("placeholder") or "").strip()
    control_id = str(control.get("id") or "").strip()
    if not label and control_id:
        node = form.find("label", attrs={"for": control_id})
        if node:
            label = node.get_text(" ", strip=True)
    if not label:
        parent = control.find_parent("label")
        if parent:
            label = parent.get_text(" ", strip=True)
    return _clean_label(label or str(control.get("name") or control_id))


def parse_generic_application(html: str, url: str) -> ApplicationInspection:
    soup = BeautifulSoup(html, "html.parser")
    forms = soup.find_all("form")
    form = max(forms, key=lambda item: len(item.select("input, textarea, select")), default=None)
    if form is None:
        raise ValueError("No application form was found on this page.")
    fields: list[ApplicationField] = []
    seen: set[str] = set()
    radio_options: dict[str, list[str]] = {}
    for control in form.select("input, textarea, select"):
        kind = str(control.get("type") or control.name or "text").casefold()
        if kind in {"hidden", "submit", "button", "reset"}:
            continue
        label = _label(control, form)
        if kind == "file":
            label = label or "Resume"
        if kind == "radio":
            group = _key(str(control.get("name") or label))
            option = str(control.get("value") or label).strip()
            radio_options.setdefault(group, []).append(option)
            if group in seen:
                continue
            label = _clean_label(str(control.get("name") or label).replace("-", " "))
            key = group
        else:
            key = _key(label)
        if not key or key in seen:
            continue
        seen.add(key)
        label_lower = label.casefold()
        if kind == "file":
            section = "cover_letter" if "cover" in label_lower else "resume"
            key = "cover_letter" if section == "cover_letter" else "resume"
        elif kind in {"radio", "checkbox", "select"}:
            section = "questions"
        else:
            section = "contact_details"
        options = tuple(_clean_label(node.get_text(" ", strip=True)) for node in control.select("option") if node.get("value") != "")
        fields.append(ApplicationField(section, key, label, "select" if kind in {"radio", "select"} else kind,
                                       bool(control.has_attr("required")) or kind == "radio", options, len(fields) + 1))
    fields = [
        ApplicationField(f.section, f.field_key, f.label, f.field_type, f.required,
                         tuple(radio_options.get(f.field_key, f.options)), f.position)
        for f in fields
    ]
    text = html.casefold()
    return ApplicationInspection(
        provider="generic_web_form", application_url=url, current_page="application_form", fields=tuple(fields),
        privacy_consent_required="privacy" in text and ("agree" in text or "consent" in text),
        captcha_required="recaptcha" in text or "hcaptcha" in text,
        notes=("Fields were discovered from the rendered employer form by the generic application agent.",),
    )


def inspect_generic_application(url: str) -> ApplicationInspection:
    with PlaywrightBrowserClient(headless=True, delay_ms=0) as browser:
        result = browser.get_page_html(url, extra_wait_ms=1500)
    if result.blocked_reason:
        raise RuntimeError(f"Application page was blocked: {result.blocked_reason}")
    return parse_generic_application(result.html, result.final_url or url)


def submit_generic_application(url: str, values: dict[str, str]) -> str:
    """Rediscover controls, map reviewed values by normalized labels, fill, and submit."""
    with PlaywrightBrowserClient(headless=True, delay_ms=0) as browser:
        page = browser._context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            form = page.locator("form").filter(has=page.locator("input[type=file]")).first
            controls = form.locator("input:not([type=hidden]):not([type=submit]), textarea, select")
            for control in controls.all():
                kind = (control.get_attribute("type") or control.evaluate("el => el.tagName.toLowerCase()")).casefold()
                name = control.get_attribute("name") or ""
                label = control.get_attribute("aria-label") or control.get_attribute("placeholder") or name or control.get_attribute("id") or ""
                key = _key(name if kind == "radio" else label)
                if kind == "file":
                    key = "cover_letter" if "cover" in label.casefold() else "resume"
                    path = Path(values.get(key, "")).expanduser()
                    if path.is_file():
                        control.set_input_files(str(path.resolve()))
                elif kind == "radio":
                    if str(control.get_attribute("value") or "").casefold() == values.get(key, "").casefold():
                        control.check()
                elif kind == "checkbox":
                    if values.get(key, "").casefold() in {"yes", "true", "checked"}:
                        control.check()
                elif kind == "select":
                    control.select_option(label=values.get(key, ""))
                elif key in values:
                    control.fill(values[key])
            form.locator("button[type=submit], input[type=submit]").first.click()
            page.wait_for_timeout(2500)
            body = page.locator("body").inner_text().casefold()
            if "thank" not in body and "success" not in body and "received" not in body:
                raise RuntimeError("The form was sent, but the employer site did not show a recognizable confirmation.")
            return page.url
        finally:
            page.close()
