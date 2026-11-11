"""Scheduled discovery remains bounded and does not launch model scoring."""

from types import SimpleNamespace

from src.jobs.run_scheduled_discovery import run_scheduled_discovery


def test_board_dry_run_does_not_log_to_database(monkeypatch):
    from src.jobs.board_discovery.runner import run_board_discovery

    monkeypatch.setattr(
        "src.jobs.board_discovery.runner.load_board_sources_config",
        lambda: SimpleNamespace(defaults={}, boards=[]),
    )
    monkeypatch.setattr(
        "src.jobs.board_discovery.runner._log_run",
        lambda summary: (_ for _ in ()).throw(AssertionError("logged dry run")),
    )
    assert run_board_discovery(dry_run=True).dry_run


def test_daily_run_uses_only_enabled_low_phase_boards_and_ats(monkeypatch):
    called = []
    boards = [
        SimpleNamespace(source_id="jobbank", enabled=True, phase=1),
        SimpleNamespace(source_id="biospace", enabled=True, phase=1),
        SimpleNamespace(source_id="indeed_ca", enabled=True, phase=3),
        SimpleNamespace(source_id="disabled", enabled=False, phase=1),
    ]
    monkeypatch.setattr("src.jobs.run_scheduled_discovery.load_board_sources_config", lambda: SimpleNamespace(boards=boards))
    monkeypatch.setattr("src.jobs.run_scheduled_discovery.run_board_discovery", lambda **kw: called.append(("boards", kw)) or SimpleNamespace(run_id=kw["run_id"], inserted=2, board_stats=[]))
    monkeypatch.setattr("src.jobs.run_scheduled_discovery.run_employer_ats_discovery", lambda **kw: called.append(("ats", kw)) or SimpleNamespace(run_id=kw["run_id"], inserted=1, sources_registered=2, sources_checked=2, source_stats=[]))
    monkeypatch.setattr("src.jobs.run_scheduled_discovery._ready_jobs", lambda run_ids: [])

    result = run_scheduled_discovery()

    assert called[0][0] == "boards"
    assert called[0][1]["board_ids"] == ["jobbank", "biospace"]
    assert called[1][0] == "ats"
    assert called[1][1]["max_embedded_fetches"] == 20
    assert called[1][1]["max_sources"] == 50
    assert called[0][1]["run_id"] == called[1][1]["run_id"] == result["run_id"]
    assert result["discovery_run_ids"] == [result["run_id"]]
    assert result["boards_skipped"] == [
        {"source_id": "indeed_ca", "reason": "outside_selected_phase"},
        {"source_id": "disabled", "reason": "disabled"},
    ]


def test_weekly_run_selects_every_enabled_board(monkeypatch):
    selected = []
    boards = [
        SimpleNamespace(source_id="jobbank", enabled=True, phase=1),
        SimpleNamespace(source_id="indeed_ca", enabled=True, phase=3),
        SimpleNamespace(source_id="disabled", enabled=False, phase=3),
    ]
    monkeypatch.setattr("src.jobs.run_scheduled_discovery.load_board_sources_config", lambda: SimpleNamespace(boards=boards))
    monkeypatch.setattr("src.jobs.run_scheduled_discovery.run_board_discovery", lambda **kw: selected.extend(kw["board_ids"]) or SimpleNamespace(run_id=kw["run_id"], inserted=0, board_stats=[]))
    monkeypatch.setattr("src.jobs.run_scheduled_discovery.run_employer_ats_discovery", lambda **kw: SimpleNamespace(run_id=kw["run_id"], inserted=0, sources_registered=0, sources_checked=0, source_stats=[]))
    result = run_scheduled_discovery(all_boards=True, dry_run=True)

    assert selected == ["jobbank", "indeed_ca"]
    assert result["boards_skipped"] == [{"source_id": "disabled", "reason": "disabled"}]
    assert result["board_scope"] == "all_enabled"


def test_zero_result_board_is_reported_as_unverified(monkeypatch):
    boards = [SimpleNamespace(source_id="google_jobs", enabled=True, phase=3)]
    stats = SimpleNamespace(source_id="google_jobs", raw_jobs=0, filtered_jobs=0, queries_run=7, notes="")
    monkeypatch.setattr("src.jobs.run_scheduled_discovery.load_board_sources_config", lambda: SimpleNamespace(boards=boards))
    monkeypatch.setattr("src.jobs.run_scheduled_discovery.run_board_discovery", lambda **kw: SimpleNamespace(run_id=kw["run_id"], inserted=0, board_stats=[stats]))
    monkeypatch.setattr("src.jobs.run_scheduled_discovery.run_employer_ats_discovery", lambda **kw: SimpleNamespace(run_id=kw["run_id"], inserted=0, sources_registered=0, sources_checked=0, source_stats=[]))
    result = run_scheduled_discovery(all_boards=True, dry_run=True)

    assert result["warnings"] == ["google_jobs: zero results; source coverage unverified"]
    assert result["errors"] == []


def test_browser_launch_failure_still_runs_http_boards_and_ats(monkeypatch):
    boards = [
        SimpleNamespace(source_id="jobbank", enabled=True, phase=1, scrape_mode="requests"),
        SimpleNamespace(source_id="indeed_ca", enabled=True, phase=3, scrape_mode="playwright"),
    ]
    calls = []
    def board_scan(**kwargs):
        calls.append(kwargs["board_ids"])
        if "indeed_ca" in kwargs["board_ids"]:
            raise RuntimeError("Chromium permission denied")
        return SimpleNamespace(run_id=kwargs["run_id"], inserted=1, board_stats=[])
    monkeypatch.setattr("src.jobs.run_scheduled_discovery.load_board_sources_config", lambda: SimpleNamespace(boards=boards))
    monkeypatch.setattr("src.jobs.run_scheduled_discovery.run_board_discovery", board_scan)
    monkeypatch.setattr("src.jobs.run_scheduled_discovery.run_employer_ats_discovery", lambda **kw: SimpleNamespace(run_id=kw["run_id"], inserted=0, sources_registered=0, sources_checked=0, source_stats=[]))
    result = run_scheduled_discovery(all_boards=True, dry_run=True)

    assert calls == [["jobbank", "indeed_ca"], ["jobbank"]]
    assert result["boards_unattempted"] == ["indeed_ca"]
    assert "Chromium permission denied" in result["errors"][0]
    assert result["boards"]["inserted"] == 1


def test_dry_run_is_forwarded_to_all_sources(monkeypatch):
    calls = []
    monkeypatch.setattr("src.jobs.run_scheduled_discovery.load_board_sources_config", lambda: SimpleNamespace(boards=[]))
    monkeypatch.setattr("src.jobs.run_scheduled_discovery.run_employer_ats_discovery", lambda **kw: calls.append(kw) or SimpleNamespace(run_id="ats", inserted=0, sources_registered=0, sources_checked=0, source_stats=[]))
    result = run_scheduled_discovery(dry_run=True)
    assert calls[0]["dry_run"] is True
    assert result["discovery_run_ids"] == []


def test_career_scan_disables_legacy_model_scoring(monkeypatch):
    from src.jobs.discovery_config import DiscoveryConfig, PrescreenConfig, BudgetConfig, LLMTriageConfig, LLMFitConfig

    config = DiscoveryConfig(
        prescreen=PrescreenConfig(), budgets=BudgetConfig(),
        llm_triage=LLMTriageConfig(enabled=True), llm_fit=LLMFitConfig(enabled=True),
        search_queries=[], location_filters=[], budgets_by_size={},
    )
    seen = []
    monkeypatch.setattr("src.jobs.run_scheduled_discovery.load_board_sources_config", lambda: SimpleNamespace(boards=[]))
    monkeypatch.setattr("src.jobs.run_scheduled_discovery.load_discovery_config", lambda: config)
    monkeypatch.setattr("src.jobs.run_scheduled_discovery._career_offset", lambda limit: 12)
    monkeypatch.setattr("src.jobs.run_scheduled_discovery.run_employer_ats_discovery", lambda **kw: SimpleNamespace(run_id="ats", inserted=0, sources_registered=0, sources_checked=0, source_stats=[]))
    monkeypatch.setattr("src.jobs.run_scheduled_discovery.run_job_discovery", lambda **kw: seen.append(kw) or SimpleNamespace(companies_with_career_pages=2, new_jobs_inserted=1, companies_with_errors=0))
    monkeypatch.setattr("src.jobs.run_scheduled_discovery._ready_jobs", lambda run_ids: [])

    run_scheduled_discovery(include_careers=True, career_limit=2)

    assert seen[0]["limit"] == 2
    assert seen[0]["company_offset"] == 12
    assert seen[0]["discovery_run_id"]
    assert not seen[0]["discovery_config"].llm_fit.enabled
    assert not seen[0]["discovery_config"].llm_triage.enabled
