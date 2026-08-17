# ADR-012: Synchronized master career profile

**Status:** Accepted  
**Date:** 2026-08-05  
**Deciders:** Project maintainer  
**Supersedes:** None  
**Superseded by:** None

## Context

The resume-generation repository owns a comprehensive career profile, while this repository had a placeholder `user/master_cv.md` and hardcoded legacy scorer profiles. The duplicate sources could drift and produce inconsistent evaluations. This repository must remain runnable independently and evaluation agents need a local, auditable input.

## Decision

The canonical profile remains `resume-generation-pipeline/personal/master-profile.md`. Deterministic Python synchronization generates `user/master_cv.md`, records source provenance and a SHA-256 hash in its header, and provides a staleness check. Both agent skills and legacy Ollama prompts consume the generated copy. Profile content participates in legacy scorer cache keys.

Candidate evidence is interpreted as confirmed, transferable, active development, a genuine gap, or unverified. Unverified claims cannot increase scores.

## Alternatives considered

| Option | Pros | Cons |
|--------|------|------|
| Symlink | Always current | Fragile across platforms, clones, and repository layouts |
| Read sibling file directly | No copy | Job-search repository cannot operate independently |
| Generated local copy with hash | Portable, auditable, supports stale warnings | Requires an explicit sync step |

## Consequences

### Positive

- Agent and Ollama evaluations use the same detailed profile.
- A content hash detects source drift and manual edits.
- The generated copy works when only this repository is available.

### Negative / trade-offs

- Maintainers must synchronize after editing the source profile.
- The configured relative path assumes the repositories are siblings unless overridden.

### Follow-ups

- Consider adding the `--check` command to CI when both repositories are available.

## Implementation notes

- CLI: `python3 -m src.profile.master_profile [--check]`
- Configuration: `config/profile.yml` → `master_profile_sync`
- Generated file: `user/master_cv.md`

## Related

- ADRs: ADR-005, ADR-006
- Code: `src/profile/master_profile.py`, `src/llm/prompts.py`
