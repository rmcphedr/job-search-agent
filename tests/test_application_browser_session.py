from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from src.applications.browser_session import (
    BrowserPause, advance_nonfinal, fill_observed_page, observe_page,
    open_application_browser, reconcile_page,
)


@pytest.fixture
def page():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        yield page
        browser.close()


def test_two_pages_rediscovered_and_final_never_clicked(page):
    page.set_content('''<form><label>Name<input name="name"></label>
    <button type="button" onclick="document.querySelector('form').innerHTML = '<label>Experience<textarea></textarea></label><button>Submit application</button>'">Next</button></form>''')
    first = observe_page(page)
    assert fill_observed_page(page, first, {"name": "Candidate"}).filled == ("name",)
    second = advance_nonfinal(page, first)
    assert [f.field_key for f in second.fields] == ["experience"]
    assert second.page_identity != first.page_identity
    assert second.final_action.name == "Submit application"
    with pytest.raises(BrowserPause):
        advance_nonfinal(page, second)


def test_dynamic_upload(page, tmp_path):
    page.set_content('''<form><button type="button" onclick="let f=document.createElement('input');f.type='file';f.onchange=()=>document.body.dataset.upload=f.files[0].name;f.click()">Upload resume</button><button>Submit application</button></form>''')
    document = tmp_path / "resume.txt"
    document.write_text("Resume")
    observation = observe_page(page)
    assert fill_observed_page(page, observation, {"resume": str(document)}).filled == ("resume",)
    assert page.locator("body").get_attribute("data-upload") == "resume.txt"


def test_provider_validation(page):
    page.set_content('<form><label>Email<input type="email" required></label><div role="alert">Email is invalid</div><button>Next</button></form>')
    observation = observe_page(page)
    assert "Email is invalid" in observation.validation
    with pytest.raises(BrowserPause):
        advance_nonfinal(page, observation)


def test_account_handoff_reobserves_changed_page(page):
    page.set_content('<form><input type="password" aria-label="Password"><button>Sign in</button></form>')
    old = observe_page(page)
    assert "account" in old.gates
    assert not fill_observed_page(page, old, {"password": "secret"}).filled
    page.set_content('<form><label>City<input></label><button>Next</button></form>')
    resumed = reconcile_page(page, old.checkpoint())
    assert resumed.fields[0].field_key == "city"
    assert "account" not in resumed.gates


def test_restart_lost_wizard_state_reconciles(tmp_path):
    profile = tmp_path / "profile"
    with open_application_browser(1, profile_dir=profile, headless=True) as browser:
        browser.page.set_content('<form><label>Experience<textarea></textarea></label></form>')
        checkpoint = observe_page(browser.page).checkpoint()
    with open_application_browser(1, profile_dir=profile, headless=True) as browser:
        browser.page.set_content('<form><label>Name<input></label><button>Next</button></form>')
        current = browser.resume(checkpoint)
        assert browser.needs_replay
        assert current.fields[0].field_key == "name"
        assert "fields" not in checkpoint


def test_unknown_navigation_pauses(page):
    page.set_content('<form><label>Name<input></label><button>Proceed onward</button></form>')
    observation = observe_page(page)
    with pytest.raises(BrowserPause):
        advance_nonfinal(page, observation)


def test_profile_single_owner(tmp_path):
    with open_application_browser(1, profile_dir=tmp_path, headless=True):
        with pytest.raises(BrowserPause):
            with open_application_browser(2, profile_dir=tmp_path, headless=True):
                pass
