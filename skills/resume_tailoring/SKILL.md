---
name: resume-tailoring
description: Orchestrate evidence-first resume tailoring for a tracked job through the sibling resume-generation pipeline. Use when preparing a job application, generating a tailored resume, or inspecting resume artifacts and validation warnings.
---

# Resume Tailoring Bridge

Keep this repository responsible for job and application state. Keep the
sibling `resume-generation-pipeline` responsible for personal evidence,
tailoring rules, templates, validation, and DOCX output.

## Workflow

1. Require a tracked job with a stored description.
2. Create a versioned request through
   `src.integrations.resume_pipeline.create_resume_request`.
3. Invoke `run_resume_generation`; do not duplicate or directly edit the
   sibling repository's `personal/` evidence.
4. Record returned artifact paths and warnings in the `resume` application
   preparation step.
5. Mark the step complete only when the bridge reports `complete` and returns
   a DOCX path.
6. Never submit an application from this skill.

## Configuration

Read `config/settings.yaml` → `integrations.resume_pipeline`. Allow
`RESUME_PIPELINE_ROOT` to override the repository path for local environments.

## Contract

Requests and results use schema version 1 and are retained under
`data/staging/resume_requests/` and `data/staging/resume_results/`. Treat the
result as failed when warnings indicate missing drafts, validation errors,
build errors, or a missing DOCX artifact.
