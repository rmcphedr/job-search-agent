# ADR-007: Python directory scraper as discovery fallback

**Status:** Accepted  
**Date:** 2025-06-22  
**Deciders:** Project maintainer

## Context

Curated directory sources (BIOTECanada, Life Sciences BC, MaRS, Centech, CDL, Neurotech Jobs) have stable HTML structures. A deterministic scraper can extract hundreds of companies without agent cost. Agents excel at ad-hoc research and sources not in config.

## Decision

- Maintain `config/directory_sources.yaml` as canonical scrape definitions.
- `config/sources.yml` is the agent-facing index pointing to the same sources.
- CLI: `python -m src.discovery.run_directory_discovery` with `--source`, `--dry-run`, `--limit`.
- Merge via `src.discovery.update_inventory` + `src.discovery.deduplicate`.
- Agent skill `company_discovery` handles manual/web research and writes staging JSON; Python merge is equivalent end state.

Both paths produce `CompanyCandidate`-shaped records; only the discovery method differs.

## Alternatives considered

| Option | Pros | Cons |
|--------|------|------|
| Agents only | Flexible | Slow/expensive for 6 known directories |
| **Python scrape + agent research** | Fast bulk + flexible long tail | Two discovery paths |
| Third-party company API | Structured data | Cost; coverage gaps |

## Consequences

### Positive

- 273 companies seeded in inventory from directory runs.
- Per-source debug CLIs (`debug_source`, `test_source`).

### Negative / trade-offs

- Directory CLI bypasses staging (writes directly to inventory when not dry-run).
- Must add staging-aware merge for agent-only discovery (ADR-008).

### Follow-ups

- `run_directory_discovery --from-staging` or unified merge CLI.
- Event emission when new companies enter inventory.

## Related

- [src/discovery/](../../src/discovery/)
- [config/directory_sources.yaml](../../config/directory_sources.yaml)
- ADR-001, ADR-008
