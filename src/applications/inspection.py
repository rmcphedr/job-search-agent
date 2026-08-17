"""Provider routing and LinkedIn employer-site handoff discovery."""

from urllib.parse import parse_qs, unquote, urlparse

from bs4 import BeautifulSoup

from src.applications.dayforce import ApplicationInspection, inspect_dayforce_application, supports_dayforce
from src.applications.generic_form import inspect_generic_application
from src.jobs.board_discovery.playwright_client import PlaywrightBrowserClient


def resolve_linkedin_apply_url(url: str) -> str:
    """Resolve LinkedIn's visible company-site Apply link without submitting data."""
    parsed = urlparse(url)
    if "linkedin.com" not in parsed.netloc.casefold():
        return url
    with PlaywrightBrowserClient(headless=True, delay_ms=0) as browser:
        result = browser.get_page_html(url, extra_wait_ms=2000)
    soup = BeautifulSoup(result.html, "html.parser")
    link = next((node for node in soup.select("a[href]") if "apply on company website" in node.get_text(" ", strip=True).casefold()), None)
    if link is None:
        raise ValueError("LinkedIn did not expose an external Apply link. Open the employer application URL directly.")
    href = str(link.get("href") or "")
    target = parse_qs(urlparse(href).query).get("url", [href])[0]
    return unquote(target)


def inspect_application(url: str) -> ApplicationInspection:
    resolved = resolve_linkedin_apply_url(url.strip())
    if supports_dayforce(resolved):
        return inspect_dayforce_application(resolved)
    return inspect_generic_application(resolved)
