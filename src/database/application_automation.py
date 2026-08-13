"""Reusable application facts, readiness, classification, and audit logging."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from src.database.db import get_connection
from src.database.migrate import apply_migrations


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_application_fact(fact_key: str, label: str, value: str, *, value_type: str = "text", source: str = "user_confirmed", notes: str = "") -> None:
    connection = get_connection()
    try:
        apply_migrations(connection)
        connection.execute(
            """INSERT INTO application_facts (fact_key, label, value, value_type, source, notes, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(fact_key) DO UPDATE SET label=excluded.label, value=excluded.value,
            value_type=excluded.value_type, source=excluded.source, notes=excluded.notes,
            updated_at=excluded.updated_at;""",
            (fact_key, label, str(value), value_type, source, notes, _now()),
        )
        connection.commit()
    finally:
        connection.close()


def list_application_facts() -> list[dict[str, Any]]:
    connection = get_connection()
    try:
        apply_migrations(connection)
        connection.commit()
        return [dict(row) for row in connection.execute("SELECT * FROM application_facts ORDER BY label;").fetchall()]
    finally:
        connection.close()


def record_application_event(event_type: str, *, job_id: int | None = None, provider: str = "", target_key: str = "", outcome: str = "success", details: dict[str, Any] | None = None) -> None:
    """Append an audit event. Details must not contain field values or secrets."""
    connection = get_connection()
    try:
        apply_migrations(connection)
        connection.execute(
            """INSERT INTO application_audit_events
            (job_id, provider, event_type, target_key, outcome, details_json)
            VALUES (?, ?, ?, ?, ?, ?);""",
            (job_id, provider, event_type, target_key, outcome, json.dumps(details or {})),
        )
        connection.commit()
    finally:
        connection.close()


def list_application_events(job_id: int) -> list[dict[str, Any]]:
    connection = get_connection()
    try:
        apply_migrations(connection)
        connection.commit()
        return [dict(row) for row in connection.execute(
            "SELECT * FROM application_audit_events WHERE job_id = ? ORDER BY event_id;", (job_id,)
        ).fetchall()]
    finally:
        connection.close()


def classify_application(provider: str, *, captcha: bool, consent: bool, requires_account: bool) -> tuple[str, str]:
    if provider.casefold() not in {"dayforce", "generic_web_form"}:
        return "manual", f"No form-filling adapter is available for {provider or 'this provider'}."
    gates = [name for enabled, name in ((captcha, "CAPTCHA"), (consent, "consent"), (requires_account, "account creation")) if enabled]
    if gates:
        return "assisted", "Provider adapter is available; human gates: " + ", ".join(gates) + "."
    return "automatable", "Known provider with no detected gate before final user submission."


def application_readiness(job_id: int) -> dict[str, Any]:
    connection = get_connection()
    try:
        apply_migrations(connection)
        connection.commit()
        rows = [dict(row) for row in connection.execute(
            "SELECT * FROM application_fields WHERE job_id = ? ORDER BY position;", (job_id,)
        ).fetchall()]
    finally:
        connection.close()
    required_missing = [row["label"] for row in rows if row["required"] and not str(row.get("value") or "").strip()]
    optional_missing = [row["label"] for row in rows if not row["required"] and not str(row.get("value") or "").strip() and row.get("disposition") != "skipped"]
    skipped = [row["label"] for row in rows if row.get("disposition") == "skipped"]
    validation_errors = [{"field": row["label"], "error": row["validation_error"]} for row in rows if row.get("validation_error")]
    return {"ready": not required_missing and not validation_errors, "required_missing": required_missing,
            "optional_missing": optional_missing, "skipped": skipped, "validation_errors": validation_errors,
            "required_count": sum(bool(row["required"]) for row in rows),
            "optional_count": sum(not bool(row["required"]) for row in rows)}


def set_field_observation(job_id: int, field_key: str, *, validation_error: str | None = None, disposition: str | None = None) -> None:
    if disposition not in {None, "pending", "provided", "skipped", "not_applicable", "human_required"}:
        raise ValueError(f"Invalid field disposition: {disposition}")
    connection = get_connection()
    try:
        apply_migrations(connection)
        connection.execute(
            """UPDATE application_fields SET validation_error = ?, disposition = COALESCE(?, disposition),
            last_observed_at = ?, updated_at = ? WHERE job_id = ? AND field_key = ?;""",
            (validation_error, disposition, _now(), _now(), job_id, field_key),
        )
        connection.commit()
    finally:
        connection.close()
