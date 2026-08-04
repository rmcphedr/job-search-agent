"""Generic HTML list adapter driven by config selectors."""

from __future__ import annotations

from urllib.parse import quote_plus

from src.jobs.board_discovery.config import BoardSource
from src.jobs.board_discovery.http import BoardHttpClient
from src.jobs.board_discovery.parsers import parse_html_list_page
from src.jobs.job_models import JobCandidate


class HtmlListAdapter:
    source_id = "html_list"

    def search(
        self,
        query: str,
        *,
        location: str,
        source: BoardSource,
        client: BoardHttpClient,
        max_pages: int,
    ) -> list[JobCandidate]:
        if not source.search_url_template:
            return []

        candidates: list[JobCandidate] = []
        encoded_query = quote_plus(query)

        for page in range(1, max_pages + 1):
            search_url = source.search_url_template.format(query=encoded_query, location=quote_plus(location))
            if page > 1 and "{page}" in source.search_url_template:
                search_url = source.search_url_template.format(
                    query=encoded_query,
                    location=quote_plus(location),
                    page=page,
                )
            try:
                html = client.get(search_url)
            except Exception:
                break
            page_candidates = parse_html_list_page(html, source=source, search_url=search_url)
            if not page_candidates:
                break
            candidates.extend(page_candidates)

        return candidates
