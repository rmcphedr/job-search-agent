# ADR-019: Human-reviewed application agent

**Status:** Accepted  
**Date:** 2026-08-06  
**Deciders:** Project maintainer and coding agent

## Context

Application systems differ in fields, documents, account requirements,
questionnaires, consent gates, and navigation. The dashboard needs an agentic
workflow without silently transmitting unreviewed personal information or
submitting an application.

## Decision

Create a persistent application workspace per tracked job. A provider adapter
uses a rendered browser to inspect the application and stores normalized,
editable fields and document requirements. Every section is reviewable before
browser filling. Privacy consent, CAPTCHA, account creation, and final
submission are explicit human gates. The first adapter supports Dayforce guest
applications. A generic rendered-form agent discovers ordinary employer-hosted
single-page forms and can submit reviewed values after an explicit dashboard
confirmation. Provider adapters remain reserved for ATS flows whose navigation
or controls cannot be handled by the generic contract.

The employer application URL is stored separately from the discovery URL.
Questionnaire inspection occurs only after reviewed candidate information is
entered and the user authorizes navigation to the next page.

Generated DOCX resumes are rendered in a rich-text editor inside the workspace.
Saving replaces the body of the existing DOCX atomically, retains its document
styles, sections, headers, and footers, and keeps the application field pointed
at the same absolute path. The editor supports the resume formatting subset used
by the pipeline: headings, paragraphs, bold, italic, underline, and lists.
Cover letters use the same editor and save behavior. Their generation button
calls a dedicated cover-letter-only bridge, which may read an existing resume
as context but never creates, modifies, validates, or rebuilds one. It stores
the returned `CoverLetter_*.docx` path in the normalized application field and
records warnings and artifact paths on the cover-letter preparation step.

The workspace uses a master-detail layout instead of stacked expanders. Section
navigation stays in a narrow left rail and the selected review surface opens in
the adjacent pane. Document sections split that pane between structured editing
and a rendered preview. LibreOffice PDF is preferred for multi-page fidelity;
macOS Quick Look provides a high-resolution one-page fallback.

Reusable questionnaire facts are stored separately from job-specific fields and
must carry explicit user-confirmed provenance. Application actions use an
append-only audit log that records field keys and outcomes without duplicating
sensitive values. Each provider session is classified as `automatable`,
`assisted`, or `manual`; this classification never removes the CAPTCHA,
attestation, consent, or final-submit human gates. Field observations distinguish
required and optional inputs, explicit skips, and provider validation errors.

When the user completes browser-only steps, the dashboard reconciles rather
than attempting to infer browser history. Explicit confirmation creates an
immutable local submission snapshot of the reviewed contact data, document
paths, questionnaire facts, and optional-field dispositions, then atomically
moves the job to Applied. Applied views are read-only and expose that snapshot
in expandable Contact details, Resume, Cover letter, and Questions sections.

## Consequences

- Contact, resume, cover-letter, document, and question sections are editable
  independently of the employer UI.
- Application inspection and progress have durable local records.
- Adapters do not accept consent, solve CAPTCHA, create accounts, or press final
  submit without an explicit, provider-specific dashboard confirmation.
- Provider-specific adapters remain necessary for reliable interaction.
- Complex Word-only body constructs such as tables and floating objects are not
  part of the inline editing contract and should be edited in Word when needed.

## Implementation

- `src/applications/dayforce.py`
- `src/applications/generic_form.py`
- `src/applications/inspection.py`
- `src/database/application_workspace.py`
- `src/database/application_automation.py`
- `src/documents/resume_editor.py`
- `src/ui/tracking_view.py`
- `application_sessions` and `application_fields` SQLite tables
