---
name: application-answering
description: Draft one evidence-backed answer to an employer application question.
---

Read the request JSON path in the prompt. Return a single JSON object at OUTPUT_PATH with `field_key`, `answer`, `evidence_refs`, and `approval_status`.

Use candidate-owned profile files and explicitly user-confirmed application facts as factual evidence. Cite their exact keys in `evidence_refs` (`user/...` or `application_facts:<fact_key>`). A generated resume or cover letter is output, never factual evidence. If `user/master_cv.md` is absent from the request, do not use it: the synchronization check may have excluded it.

Draft a useful, truthful answer to an unfamiliar question, but mark it `approval_required`. Do not invent credentials or personal disclosures. Work authorization, compensation, legal attestations, demographic fields, and consent require explicit confirmed facts or direct user action. Python validates and may override your status. Never write SQLite or canonical CSV files.
