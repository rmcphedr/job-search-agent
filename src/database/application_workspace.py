"""Persistence for inspected application fields and user-reviewed drafts."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.applications.dayforce import ApplicationInspection
from src.database.application_automation import classify_application, record_application_event
from src.database.db import get_connection
from src.database.migrate import apply_migrations


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_inspection(job_id: int, inspection: ApplicationInspection) -> None:
    connection = get_connection()
    try:
        apply_migrations(connection)
        now = _now()
        automation_class, classification_reason = classify_application(
            inspection.provider,
            captcha=inspection.captcha_required,
            consent=inspection.privacy_consent_required,
            requires_account=inspection.requires_account,
        )
        connection.execute(
            """
            INSERT INTO application_sessions
                (job_id, application_url, provider, status, current_page,
                 requires_account, privacy_consent_required, captcha_required,
                 last_inspected_at, updated_at, automation_class, classification_reason)
            VALUES (?, ?, ?, 'inspected', ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                application_url=excluded.application_url,
                provider=excluded.provider,
                status='inspected', current_page=excluded.current_page,
                requires_account=excluded.requires_account,
                privacy_consent_required=excluded.privacy_consent_required,
                captcha_required=excluded.captcha_required,
                last_inspected_at=excluded.last_inspected_at,
                last_error=NULL, updated_at=excluded.updated_at,
                automation_class=excluded.automation_class,
                classification_reason=excluded.classification_reason;
            """,
            (
                job_id, inspection.application_url, inspection.provider,
                inspection.current_page, int(inspection.requires_account),
                int(inspection.privacy_consent_required), int(inspection.captcha_required),
                now, now, automation_class, classification_reason,
            ),
        )
        for item in inspection.fields:
            connection.execute(
                """
                INSERT INTO application_fields
                    (job_id, section, field_key, label, field_type, required,
                     options_json, position, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id, field_key) DO UPDATE SET
                    section=excluded.section, label=excluded.label,
                    field_type=excluded.field_type, required=excluded.required,
                    options_json=excluded.options_json, position=excluded.position,
                    updated_at=excluded.updated_at;
                """,
                (
                    job_id, item.section, item.field_key, item.label, item.field_type,
                    int(item.required), json.dumps(item.options), item.position, now,
                ),
            )
        keys = [item.field_key for item in inspection.fields]
        if keys:
            placeholders = ",".join("?" for _ in keys)
            connection.execute(
                f"DELETE FROM application_fields WHERE job_id = ? AND field_key NOT IN ({placeholders}) AND COALESCE(value, '') = '';",
                (job_id, *keys),
            )
        connection.commit()
    finally:
        connection.close()
    record_application_event(
        "inspection_saved", job_id=job_id, provider=inspection.provider,
        details={"field_count": len(inspection.fields), "automation_class": automation_class},
    )


def get_application_workspace(job_id: int) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    connection = get_connection()
    try:
        apply_migrations(connection)
        connection.commit()
        session = connection.execute(
            "SELECT * FROM application_sessions WHERE job_id = ?;", (job_id,)
        ).fetchone()
        fields = connection.execute(
            "SELECT * FROM application_fields WHERE job_id = ? ORDER BY position, field_id;",
            (job_id,),
        ).fetchall()
        return (dict(session) if session else None, [dict(row) for row in fields])
    finally:
        connection.close()


def update_application_field(job_id: int, field_key: str, value: str) -> None:
    connection = get_connection()
    try:
        connection.execute(
            """
            UPDATE application_fields
            SET value = ?, status = CASE WHEN TRIM(?) = '' THEN 'missing' ELSE 'reviewed' END,
                disposition = CASE WHEN TRIM(?) = '' THEN 'pending' ELSE 'provided' END,
                validation_error = NULL,
                updated_at = ?
            WHERE job_id = ? AND field_key = ?;
            """,
            (value, value, value, _now(), job_id, field_key),
        )
        connection.commit()
    finally:
        connection.close()
    record_application_event(
        "field_reviewed", job_id=job_id, target_key=field_key,
        details={"provided": bool(value.strip())},
    )


def prefill_from_master_profile(job_id: int, profile_path="user/master_cv.md") -> int:
    """Prefill confirmed contact facts without overwriting reviewed values."""
    text = Path(profile_path).read_text(encoding="utf-8")

    def fact(label: str) -> str:
        match = re.search(rf"^- \*\*{re.escape(label)}:\*\*\s*(.+)$", text, flags=re.MULTILINE)
        return match.group(1).strip() if match else ""

    name = re.sub(r",?\s*PhD\s*$", "", fact("Name"), flags=re.IGNORECASE).strip()
    name_parts = name.split()
    location_parts = [part.strip() for part in fact("Location").split(",")]
    province = {"QC": "Quebec"}.get(location_parts[1] if len(location_parts) > 1 else "", location_parts[1] if len(location_parts) > 1 else "")
    values = {
        "email_address": fact("Email"),
        "confirm_email_address": fact("Email"),
        "first_name": name_parts[0] if name_parts else "",
        "last_name": name_parts[-1] if len(name_parts) > 1 else "",
        "linkedin_profile": fact("LinkedIn"),
        "country_dialing_code": "+1",
        "mobile_phone_number": fact("Phone"),
        "preferred_contact_method": "Email",
        "country": location_parts[2] if len(location_parts) > 2 else "Canada",
        "state_province": province,
        "city": location_parts[0] if location_parts else "",
        "how_did_you_hear_about_this_job": "LinkedIn",
        "your_name": name,
        "your_email": fact("Email"),
        "address": fact("Location"),
        "phone_number": fact("Phone"),
    }
    connection = get_connection()
    try:
        updated = 0
        now = _now()
        for key, value in values.items():
            if not value:
                continue
            cursor = connection.execute(
                """
                UPDATE application_fields
                SET value = ?, status = 'draft', updated_at = ?
                WHERE job_id = ? AND field_key = ? AND COALESCE(value, '') = '';
                """,
                (value, now, job_id, key),
            )
            updated += cursor.rowcount
        connection.commit()
        return updated
    finally:
        connection.close()


def prefill_generated_resume(job_id: int) -> bool:
    """Link a completed resume-pipeline DOCX into the application draft."""
    connection = get_connection()
    try:
        row = connection.execute(
            """
            SELECT details FROM application_preparation_steps
            WHERE job_id = ? AND step_key = 'resume' AND status = 'complete';
            """,
            (job_id,),
        ).fetchone()
        if row is None:
            return False
        match = re.search(r"^Resume DOCX:\s*(.+)$", str(row["details"] or ""), flags=re.MULTILINE)
        if not match:
            return False
        path = match.group(1).strip()
        cursor = connection.execute(
            """
            UPDATE application_fields
            SET value = ?, status = 'draft', updated_at = ?
            WHERE job_id = ? AND field_key = 'resume' AND COALESCE(value, '') = '';
            """,
            (path, _now(), job_id),
        )
        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()


def prefill_generated_cover_letter(job_id: int) -> bool:
    """Link a completed cover-letter DOCX into an empty application field."""
    connection = get_connection()
    try:
        row = connection.execute(
            """
            SELECT details FROM application_preparation_steps
            WHERE job_id = ? AND step_key = 'cover_letter' AND status = 'complete';
            """,
            (job_id,),
        ).fetchone()
        if row is None:
            return False
        match = re.search(
            r"^Cover letter DOCX:\s*(.+)$",
            str(row["details"] or ""),
            flags=re.MULTILINE | re.IGNORECASE,
        )
        if not match:
            return False
        path = match.group(1).strip()
        if not Path(path).expanduser().is_file():
            return False
        cursor = connection.execute(
            """
            UPDATE application_fields
            SET value = ?, status = 'draft', updated_at = ?
            WHERE job_id = ? AND field_key = 'cover_letter' AND COALESCE(value, '') = '';
            """,
            (path, _now(), job_id),
        )
        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()
