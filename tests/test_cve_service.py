from __future__ import annotations

import pytest

from digagent.cve_service import CveService
from digagent.storage import FileStorage


def _payload(*items: dict[str, object]) -> dict[str, object]:
    return {"vulnerabilities": [{"cve": item} for item in items]}


def _cve(
    cve_id: str,
    *,
    description: str,
    cwe: str = "CWE-79",
    cpe: str = "cpe:2.3:a:acme:widget:*:*:*:*:*:*:*:*",
) -> dict[str, object]:
    return {
        "id": cve_id,
        "published": "2026-01-01T00:00:00.000Z",
        "lastModified": "2026-01-02T00:00:00.000Z",
        "descriptions": [{"lang": "en", "value": description}],
        "weaknesses": [{"description": [{"lang": "en", "value": cwe}]}],
        "configurations": [{"nodes": [{"cpeMatch": [{"criteria": cpe}]}]}],
        "references": [{"url": f"https://example.invalid/{cve_id.lower()}", "source": "NVD", "tags": ["Vendor Advisory"]}],
        "metrics": {
            "cvssMetricV31": [{
                "cvssData": {"baseScore": 8.8, "baseSeverity": "HIGH", "vectorString": "CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H"},
            }],
        },
    }


class FakeNvdClient:
    def __init__(self) -> None:
        self.page_calls: list[tuple[int, int]] = []
        self.query_calls: list[dict[str, object]] = []

    async def fetch_page(self, *, start_index: int, results_per_page: int) -> dict[str, object]:
        self.page_calls.append((start_index, results_per_page))
        return {
            "startIndex": start_index,
            "resultsPerPage": 1,
            "totalResults": 1,
            **_payload(_cve("CVE-2026-0001", description="Widget XSS in sync payload")),
        }

    async def query_cves(
        self,
        *,
        query: str = "",
        cve_id: str | None = None,
        cwe: str | None = None,
        limit: int = 20,
        modified_within_days: int | None = None,
        published_within_days: int | None = None,
    ) -> dict[str, object]:
        self.query_calls.append({
            "query": query,
            "cve_id": cve_id,
            "cwe": cwe,
            "limit": limit,
            "modified_within_days": modified_within_days,
            "published_within_days": published_within_days,
        })
        return _payload(_cve("CVE-2026-0002", description="Widget RCE from online fetch", cwe="CWE-94"))

    async def fetch_history(self, *, cve_id: str, limit: int = 20) -> dict[str, object]:
        return {
            "cveChanges": [{"cveId": cve_id, "change": "modified"}],
        }


class FakeKevClient:
    async def fetch_catalog(self) -> dict[str, object]:
        return {
            "vulnerabilities": [{
                "cveID": "CVE-2026-0002",
                "dateAdded": "2026-01-05",
                "dueDate": "2026-01-12",
                "knownRansomwareCampaignUse": "Known",
            }],
        }


@pytest.mark.asyncio
async def test_fetch_online_caches_results_and_marks_kev(test_settings) -> None:
    service = CveService(
        settings=test_settings,
        storage=FileStorage(test_settings),
        nvd_client=FakeNvdClient(),
        kev_client=FakeKevClient(),
    )

    payload = await service.fetch_online(
        cve_id="CVE-2026-0002",
        include_history=True,
    )

    assert payload["history"] == [{"cveId": "CVE-2026-0002", "change": "modified"}]
    assert payload["items"][0]["cve_id"] == "CVE-2026-0002"
    assert payload["items"][0]["kev"] is True
    assert payload["items"][0]["source"] == "nvd+kev"

    cached = service.search_local(cve_id="CVE-2026-0002")
    assert len(cached) == 1
    assert cached[0].kev is True
    assert cached[0].affected_products == ["acme:widget"]


@pytest.mark.asyncio
async def test_sync_sources_persists_state_and_supports_local_search(test_settings) -> None:
    nvd_client = FakeNvdClient()
    service = CveService(
        settings=test_settings,
        storage=FileStorage(test_settings),
        nvd_client=nvd_client,
        kev_client=FakeKevClient(),
    )

    state = await service.sync_sources(max_records=1, page_size=50)

    assert state.status == "completed"
    assert state.normalized_records == 1
    assert state.kev_records == 0
    assert nvd_client.page_calls == [(0, 50)]

    local_matches = service.search_local(query="widget")
    assert len(local_matches) == 1
    assert local_matches[0].cve_id == "CVE-2026-0001"
    assert local_matches[0].kev is False
