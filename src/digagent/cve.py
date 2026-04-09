from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import httpx

from digagent.config import AppSettings, get_settings
from digagent.models import CVERecord, CveSyncState
from digagent.storage import FileStorage
from digagent.utils import action_digest, normalize_domain, utc_now

TOKEN_RE = re.compile(r"[A-Za-z0-9._-]{3,}")


class CveKnowledgeBase:
    def __init__(self, settings: AppSettings | None = None, storage: FileStorage | None = None) -> None:
        self.settings = settings or get_settings()
        self.storage = storage or FileStorage(self.settings)
        self.base_url = "https://services.nvd.nist.gov/rest/json/cves/2.0"

    async def sync(
        self,
        *,
        max_records: int | None = None,
        start_index: int = 0,
        page_size: int = 2000,
    ) -> CveSyncState:
        state = self.storage.load_cve_state()
        state.status = "running"
        state.running = True
        state.last_error = None
        state.base_url = self.base_url
        state.page_size = page_size
        state.next_start_index = start_index
        self.storage.save_cve_state(state)

        records: list[CVERecord] = []
        try:
            current = start_index
            while True:
                payload = await self.fetch_page(start_index=current, results_per_page=page_size)
                self.storage.save_cve_raw_page(current, payload)
                batch = self.normalize_payload(payload)
                if max_records is not None:
                    remaining = max_records - len(records)
                    if remaining <= 0:
                        break
                    batch = batch[:remaining]
                records.extend(batch)
                total = int(payload.get("totalResults") or len(records))
                state.total_records = total
                state.normalized_records = len(records)
                page_count = int(payload.get("resultsPerPage") or len(batch) or 0)
                current += page_count
                state.next_start_index = current
                self.storage.save_cve_state(state)
                if not batch:
                    break
                if max_records is not None and len(records) >= max_records:
                    break
                if current >= total:
                    break

            indexes = self.build_indexes(records)
            self.storage.save_cve_records(records)
            for name, mapping in indexes.items():
                self.storage.save_cve_index(name, mapping)
            source_hash = action_digest({"count": len(records), "records": [record.cve_id for record in records[:5000]]})
            state.status = "completed"
            state.running = False
            state.last_synced_at = utc_now()
            state.normalized_records = len(records)
            state.last_source_hash = source_hash
            state.next_start_index = 0
            self.storage.save_cve_state(state)
            return state
        except Exception as exc:
            state.status = "failed"
            state.running = False
            state.last_error = str(exc)
            self.storage.save_cve_state(state)
            raise

    async def fetch_page(self, *, start_index: int, results_per_page: int) -> dict[str, Any]:
        headers: dict[str, str] = {}
        if self.settings.nvd_api_key:
            headers["apiKey"] = self.settings.nvd_api_key
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            response = await client.get(
                self.base_url,
                params={"startIndex": start_index, "resultsPerPage": results_per_page},
                headers=headers,
            )
            response.raise_for_status()
            return response.json()

    def normalize_payload(self, payload: dict[str, Any]) -> list[CVERecord]:
        records: list[CVERecord] = []
        for item in payload.get("vulnerabilities", []):
            cve = item.get("cve", {})
            cve_id = str(cve.get("id") or "").strip()
            if not cve_id:
                continue
            descriptions = [entry.get("value", "").strip() for entry in cve.get("descriptions", []) if entry.get("value")]
            cwes: list[str] = []
            for weakness in cve.get("weaknesses", []):
                for description in weakness.get("description", []):
                    value = str(description.get("value") or "").strip()
                    if value.startswith("CWE-") or value.startswith("NVD-CWE-"):
                        cwes.append(value)
            products: list[str] = []
            for configuration in cve.get("configurations", []):
                products.extend(self._extract_products(configuration))
            metrics = self._extract_metrics(cve.get("metrics", {}))
            references = [
                {"url": ref.get("url"), "source": ref.get("source"), "tags": ref.get("tags", [])}
                for ref in cve.get("references", [])
                if ref.get("url")
            ]
            keywords = self._build_keywords(cve_id, descriptions, cwes, products)
            records.append(
                CVERecord(
                    cve_id=cve_id,
                    published_at=cve.get("published"),
                    updated_at=cve.get("lastModified"),
                    descriptions=descriptions,
                    cwes=self._dedupe_case_sensitive(cwes),
                    affected_products=self._dedupe_lower(products),
                    cvss=metrics,
                    references=references,
                    keywords=keywords,
                    source_hash=action_digest(cve),
                )
            )
        return records

    def build_indexes(self, records: list[CVERecord]) -> dict[str, dict[str, list[str]]]:
        by_id: dict[str, list[str]] = {}
        by_cwe: dict[str, set[str]] = defaultdict(set)
        by_product: dict[str, set[str]] = defaultdict(set)
        by_keyword: dict[str, set[str]] = defaultdict(set)

        for record in records:
            by_id[record.cve_id] = [record.cve_id]
            for cwe in record.cwes:
                by_cwe[cwe].add(record.cve_id)
            for product in record.affected_products:
                by_product[product].add(record.cve_id)
                for token in self._tokenize(product):
                    by_keyword[token].add(record.cve_id)
            for token in record.keywords:
                by_keyword[token].add(record.cve_id)

        return {
            "by_id": by_id,
            "by_cwe": {key: sorted(value) for key, value in by_cwe.items()},
            "by_product": {key: sorted(value) for key, value in by_product.items()},
            "by_keyword": {key: sorted(value) for key, value in by_keyword.items()},
        }

    def search(
        self,
        *,
        query: str = "",
        cve_id: str | None = None,
        cwe: str | None = None,
        product: str | None = None,
        limit: int = 20,
    ) -> list[CVERecord]:
        records = {record.cve_id: record for record in self.storage.load_cve_records()}
        if not records:
            return []
        by_id = self.storage.load_cve_index("by_id")
        by_cwe = self.storage.load_cve_index("by_cwe")
        by_product = self.storage.load_cve_index("by_product")
        by_keyword = self.storage.load_cve_index("by_keyword")

        matches: set[str] = set()
        if cve_id:
            matches.update(by_id.get(cve_id.upper(), []))
        if cwe:
            matches.update(by_cwe.get(cwe.upper(), []))
        if product:
            normalized_product = product.lower()
            matches.update(by_product.get(normalized_product, []))
            for token in self._tokenize(normalized_product):
                matches.update(by_keyword.get(token, []))
        if query:
            for token in self._tokenize(query):
                matches.update(by_keyword.get(token, []))
        if not any([cve_id, cwe, product, query]):
            matches.update(list(records)[:limit])
        if query and not matches:
            lowered = query.lower()
            for record in records.values():
                haystack = " ".join(record.descriptions).lower()
                if lowered in haystack:
                    matches.add(record.cve_id)
                    if len(matches) >= limit:
                        break
        ordered = sorted((records[cve] for cve in matches if cve in records), key=lambda item: item.cve_id, reverse=True)
        return ordered[:limit]

    def state(self) -> CveSyncState:
        return self.storage.load_cve_state()

    def _extract_products(self, configuration: dict[str, Any]) -> list[str]:
        products: list[str] = []
        for node in configuration.get("nodes", []):
            for match in node.get("cpeMatch", []):
                criteria = str(match.get("criteria") or "")
                product = self._cpe_to_product(criteria)
                if product:
                    products.append(product)
            for child in node.get("children", []):
                products.extend(self._extract_products({"nodes": [child]}))
        return products

    def _cpe_to_product(self, cpe: str) -> str | None:
        parts = cpe.split(":")
        if len(parts) < 5:
            return None
        vendor = parts[3].strip().lower()
        product = parts[4].strip().lower()
        if not vendor or not product or vendor == "*" or product == "*":
            return None
        return f"{vendor}:{product}"

    def _extract_metrics(self, metrics: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2", "cvssMetricV40"):
            entries = metrics.get(key) or []
            if not entries:
                continue
            entry = entries[0]
            cvss_data = entry.get("cvssData", {})
            result[key] = {
                "baseScore": cvss_data.get("baseScore"),
                "baseSeverity": cvss_data.get("baseSeverity") or entry.get("baseSeverity"),
                "vectorString": cvss_data.get("vectorString"),
            }
        return result

    def _build_keywords(self, cve_id: str, descriptions: list[str], cwes: list[str], products: list[str]) -> list[str]:
        tokens = set(self._tokenize(cve_id))
        for description in descriptions:
            tokens.update(self._tokenize(description))
        for cwe in cwes:
            tokens.update(self._tokenize(cwe))
        for product in products:
            tokens.update(self._tokenize(product))
        return sorted(tokens)

    def _tokenize(self, value: str) -> list[str]:
        return [token.lower() for token in TOKEN_RE.findall(value or "")]

    def _dedupe(self, values: list[str]) -> list[str]:
        return self._dedupe_lower(values)

    def _dedupe_lower(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for value in values:
            cleaned = normalize_domain(value) if "://" in value else value.strip().lower()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                ordered.append(cleaned)
        return ordered

    def _dedupe_case_sensitive(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for value in values:
            cleaned = value.strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                ordered.append(cleaned)
        return ordered
