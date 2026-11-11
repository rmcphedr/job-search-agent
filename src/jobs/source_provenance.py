"""Normalize the posting provider separately from how the lead was found."""

from __future__ import annotations


SOURCE_ALIASES: dict[str, tuple[str, str]] = {
    "linkedin gmail alert": ("linkedin", "gmail_alert"),
    "linkedin_gmail_alert": ("linkedin", "gmail_alert"),
    "linkedin_email": ("linkedin", "gmail_alert"),
    "linkedin_email_alert": ("linkedin", "gmail_alert"),
    "linkedin_job_alert": ("linkedin", "gmail_alert"),
    "linkedin_alert": ("linkedin", "gmail_alert"),
    "linkedin job alerts": ("linkedin", "gmail_alert"),
    "linkedin_feed": ("linkedin", "linkedin_feed"),
    "linkedin_home_feed": ("linkedin", "linkedin_feed"),
    "glassdoor gmail alert": ("glassdoor", "gmail_alert"),
    "glassdoor_gmail_alert": ("glassdoor", "gmail_alert"),
    "glassdoor_job_alert": ("glassdoor", "gmail_alert"),
    "80000hours_email": ("80000hours", "gmail_alert"),
    "indeed": ("indeed_ca", "unknown"),
}


def normalize_source(source: str | None, channel: str | None = None) -> tuple[str | None, str | None]:
    if not source:
        return None, channel
    key = source.strip().casefold()
    canonical, inferred_channel = SOURCE_ALIASES.get(key, (key.replace(" ", "_"), "board"))
    if canonical in {"greenhouse", "lever", "ashby", "workday", "smartrecruiters", "icims"}:
        inferred_channel = "employer_ats"
    elif canonical == "company_careers":
        inferred_channel = "company_careers"
    return canonical, channel or inferred_channel
