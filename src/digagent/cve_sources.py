from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from digagent.config import AppSettings, get_settings

NVD_CVE_API = "https://services.nvd.nist.gov/rest/json/cves/2.0"
NVD_HISTORY_API = "https://services.nvd.nist.gov/rest/json/cvehistory/2.0"
KEV_CATALOG_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
HTTP_TIMEOUT_SEC = 60.0


class NvdClient:
    def __init__(self, settings: AppSettings | None = None) -> None:
        self.settings = settings or get_settings()

    async def fetch_page(self, *, start_index: int, results_per_page: int) -> dict[str, Any]:
        return await self._get_json(
            NVD_CVE_API,
            params={"startIndex": start_index, "resultsPerPage": results_per_page},
        )

    async def query_cves(
        self,
        *,
        query: str = "",
        cve_id: str | None = None,
        cwe: str | None = None,
        limit: int = 20,
        modified_within_days: int | None = None,
        published_within_days: int | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"resultsPerPage": limit}
        if cve_id:
            params["cveId"] = cve_id.upper()
        if cwe:
            params["cweId"] = cwe.upper()
        if query:
            params["keywordSearch"] = query
        if modified_within_days is not None:
            start, end = _date_window(modified_within_days)
            params["lastModStartDate"] = start
            params["lastModEndDate"] = end
        if published_within_days is not None:
            start, end = _date_window(published_within_days)
            params["pubStartDate"] = start
            params["pubEndDate"] = end
        return await self._get_json(NVD_CVE_API, params=params)

    async def fetch_history(self, *, cve_id: str, limit: int = 20) -> dict[str, Any]:
        return await self._get_json(
            NVD_HISTORY_API,
            params={"cveId": cve_id.upper(), "resultsPerPage": limit},
        )

    async def _get_json(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        headers: dict[str, str] = {}
        if self.settings.nvd_api_key:
            headers["apiKey"] = self.settings.nvd_api_key
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SEC, follow_redirects=True) as client:
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            return response.json()


class KevClient:
    async def fetch_catalog(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SEC, follow_redirects=True) as client:
            response = await client.get(KEV_CATALOG_URL)
            response.raise_for_status()
            return response.json()


def _date_window(days: int) -> tuple[str, str]:
    end = datetime.now(UTC)
    start = end - timedelta(days=days)
    return _isoformat(start), _isoformat(end)


def _isoformat(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
