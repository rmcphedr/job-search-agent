"""Board adapter protocol and registry."""

from __future__ import annotations

from typing import Protocol

from src.jobs.board_discovery.config import BoardSource
from src.jobs.board_discovery.http import BoardHttpClient
from src.jobs.job_models import JobCandidate


class BoardAdapter(Protocol):
    source_id: str

    def search(
        self,
        query: str,
        *,
        location: str,
        source: BoardSource,
        client: BoardHttpClient,
        max_pages: int,
    ) -> list[JobCandidate]:
        ...


def get_adapter(adapter_name: str) -> BoardAdapter:
    from src.jobs.board_discovery.adapters.bioinformatics_ca import BioinformaticsCaAdapter
    from src.jobs.board_discovery.adapters.biospace import BiospaceAdapter
    from src.jobs.board_discovery.adapters.can_acn import CanAcnAdapter
    from src.jobs.board_discovery.adapters.eluta import ElutaAdapter
    from src.jobs.board_discovery.adapters.healthecareers import HealthecareersAdapter
    from src.jobs.board_discovery.adapters.html_list import HtmlListAdapter
    from src.jobs.board_discovery.adapters.indeed_ca import IndeedCaAdapter
    from src.jobs.board_discovery.adapters.jobbank import JobBankAdapter
    from src.jobs.board_discovery.adapters.life_sciences_bc import LifeSciencesBcAdapter
    from src.jobs.board_discovery.adapters.neurotech import NeurotechAdapter
    from src.jobs.board_discovery.adapters.neurotechx import NeurotechXAdapter
    from src.jobs.board_discovery.adapters.stub import StubAdapter
    from src.jobs.board_discovery.adapters.wellfound import WellfoundAdapter

    registry: dict[str, BoardAdapter] = {
        "jobbank": JobBankAdapter(),
        "indeed_ca": IndeedCaAdapter(),
        "eluta": ElutaAdapter(),
        "biospace": BiospaceAdapter(),
        "bioinformatics_ca": BioinformaticsCaAdapter(),
        "life_sciences_bc": LifeSciencesBcAdapter(),
        "can_acn": CanAcnAdapter(),
        "healthecareers": HealthecareersAdapter(),
        "neurotech": NeurotechAdapter(),
        "neurotechx": NeurotechXAdapter(),
        "wellfound": WellfoundAdapter(),
        "html_list": HtmlListAdapter(),
        "stub": StubAdapter(),
    }
    adapter = registry.get(adapter_name)
    if adapter is None:
        return StubAdapter()
    return adapter
