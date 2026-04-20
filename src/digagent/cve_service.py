from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from digagent.config import AppSettings, get_settings
from digagent.cve_sources import KevClient, NvdClient
from digagent.models import CVERecord, CveSyncState
from digagent.storage import FileStorage
from digagent.utils import action_digest, normalize_domain, utc_now

TOKEN_RE = re.compile(r"[A-Za-z0-9._-]{3,}")


class CveStore:
    def __init__(self, storage: FileStorage) -> None:
        self.storage = storage

    def state(self) -> CveSyncState:
        return self.storage.load_cve_state()

    def save_state(self, state: CveSyncState) -> None:
        self.storage.save_cve_state(state)

    def merge_records(self, records: list[CVERecord]) -> list[CVERecord]:
        merged = {record.cve_id: record for record in self.storage.load_cve_records()}
        for record in records:
            merged[record.cve_id] = record
        ordered = sorted(merged.values(), key=lambda item: item.cve_id, reverse=True)
        self.storage.save_cve_records(ordered)
        for name, mapping in build_indexes(ordered).items():
            self.storage.save_cve_index(name, mapping)
        return ordered

    def search(
        self,
        *,
        query: str = "",
        cve_id: str | None = None,
        cwe: str | None = None,
        product: str | None = None,
        kev_only: bool = False,
        limit: int = 20,
    ) -> list[CVERecord]:
        records = {record.cve_id: record for record in self.storage.load_cve_records()}
        if not records:
            return []
        by_id = self.storage.load_cve_index("by_id")
        by_cwe = self.storage.load_cve_index("by_cwe")
        by_product = self.storage.load_cve_index("by_product")
        by_keyword = self.storage.load_cve_index("by_keyword")
        by_kev = set(self.storage.load_cve_index("by_kev").get("true", []))
        matches: set[str] = set()
        if cve_id:
            matches.update(by_id.get(cve_id.upper(), []))
        if cwe:
            matches.update(by_cwe.get(cwe.upper(), []))
        if product:
            lowered_product = product.lower()
            matches.update(by_product.get(lowered_product, []))
            for token in tokenize(lowered_product):
                matches.update(by_keyword.get(token, []))
        if query:
            for token in tokenize(query):
                matches.update(by_keyword.get(token, []))
        if not any([query, cve_id, cwe, product]):
            matches.update(list(records)[:limit])
        if query and not matches:
            lowered = query.lower()
            for record in records.values():
                if lowered in " ".join(record.descriptions).lower():
                    matches.add(record.cve_id)
                    if len(matches) >= limit:
                        break
        if kev_only:
            matches = matches & by_kev if matches else set(by_kev)
        ordered = sorted((records[item] for item in matches if item in records), key=_sort_key)
        return ordered[:limit]


class CveService:
    def __init__(
        self,
        settings: AppSettings | None = None,
        storage: FileStorage | None = None,
        *,
        nvd_client: NvdClient | None = None,
        kev_client: KevClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.storage = storage or FileStorage(self.settings)
        self.store = CveStore(self.storage)
        self.nvd_client = nvd_client or NvdClient(self.settings)
        self.kev_client = kev_client or KevClient()

    async def sync_sources(
        self,
        *,
        max_records: int | None = None,
        start_index: int = 0,
        page_size: int = 2000,
    ) -> CveSyncState:
        state = self.store.state()
        state.status = "running"
        state.running = True
        state.last_error = None
        state.page_size = page_size
        state.next_start_index = start_index
        self.store.save_state(state)
        kev_map = build_kev_map(await self.kev_client.fetch_catalog())
        records: list[CVERecord] = []
        try:
            current = start_index
            while True:
                payload = await self.nvd_client.fetch_page(start_index=current, results_per_page=page_size)
                self.storage.save_cve_raw_page(current, payload)
                batch = normalize_payload(payload, kev_map)
                if max_records is not None:
                    remaining = max_records - len(records)
                    if remaining <= 0:
                        break
                    batch = batch[:remaining]
                records.extend(batch)
                total = int(payload.get("totalResults") or len(records))
                page_count = int(payload.get("resultsPerPage") or len(batch) or 0)
                current += page_count
                state.total_records = total
                state.normalized_records = len(records)
                state.kev_records = sum(1 for item in records if item.kev)
                state.next_start_index = current
                self.store.save_state(state)
                if not batch or (max_records is not None and len(records) >= max_records) or current >= total:
                    break
            merged = self.store.merge_records(records)
            state.status = "completed"
            state.running = False
            state.last_synced_at = utc_now()
            state.normalized_records = len(merged)
            state.kev_records = sum(1 for item in merged if item.kev)
            state.last_source_hash = action_digest({"count": len(merged), "kev": state.kev_records})
            state.next_start_index = 0
            self.store.save_state(state)
            return state
        except Exception as exc:
            state.status = "failed"
            state.running = False
            state.last_error = str(exc)
            self.store.save_state(state)
            raise

    def search_local(self, **kwargs: Any) -> list[CVERecord]:
        return self.store.search(**kwargs)

    async def fetch_online(
        self,
        *,
        query: str = "",
        cve_id: str | None = None,
        cwe: str | None = None,
        product: str | None = None,
        kev_only: bool = False,
        limit: int = 20,
        modified_within_days: int | None = None,
        published_within_days: int | None = None,
        include_history: bool = False,
    ) -> dict[str, Any]:
        effective_query = query or (product or "")
        kev_map = build_kev_map(await self.kev_client.fetch_catalog())
        payload = await self.nvd_client.query_cves(
            query=effective_query,
            cve_id=cve_id,
            cwe=cwe,
            limit=limit,
            modified_within_days=modified_within_days,
            published_within_days=published_within_days,
        )
        items = normalize_payload(payload, kev_map)
        if kev_only:
            items = [item for item in items if item.kev]
        self.store.merge_records(items)
        history: list[dict[str, Any]] = []
        if include_history and cve_id:
            history_payload = await self.nvd_client.fetch_history(cve_id=cve_id, limit=limit)
            history = list(history_payload.get("cveChanges") or [])
        return {
            "items": [item.model_dump(mode="json") for item in items[:limit]],
            "history": history,
            "state": self.store.state().model_dump(mode="json"),
        }


def normalize_payload(payload: dict[str, Any], kev_map: dict[str, dict[str, Any]]) -> list[CVERecord]:
    records: list[CVERecord] = []
    for item in payload.get("vulnerabilities", []):
        cve = item.get("cve", {})
        cve_id = str(cve.get("id") or "").strip()
        if not cve_id:
            continue
        kev = kev_map.get(cve_id.upper(), {})
        descriptions = [entry.get("value", "").strip() for entry in cve.get("descriptions", []) if entry.get("value")]
        cwes = [str(desc.get("value") or "").strip() for weakness in cve.get("weaknesses", []) for desc in weakness.get("description", []) if str(desc.get("value") or "").strip()]
        products = [product for config in cve.get("configurations", []) for product in extract_products(config)]
        records.append(CVERecord(
            cve_id=cve_id,
            published_at=cve.get("published"),
            updated_at=cve.get("lastModified"),
            descriptions=descriptions,
            cwes=dedupe_case_sensitive([item for item in cwes if item]),
            affected_products=dedupe_lower(products),
            cvss=extract_metrics(cve.get("metrics", {})),
            references=[{"url": ref.get("url"), "source": ref.get("source"), "tags": ref.get("tags", [])} for ref in cve.get("references", []) if ref.get("url")],
            keywords=sorted({token for value in [cve_id, *descriptions, *cwes, *products] for token in tokenize(value)}),
            kev=bool(kev),
            kev_date_added=kev.get("dateAdded"),
            kev_due_date=kev.get("dueDate"),
            known_ransomware_campaign_use=kev.get("knownRansomwareCampaignUse"),
            source="nvd+kev" if kev else "nvd",
            source_hash=action_digest(cve),
        ))
    return records


def build_kev_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item.get("cveID") or "").upper(): item for item in payload.get("vulnerabilities", []) if str(item.get("cveID") or "").strip()}


def build_indexes(records: list[CVERecord]) -> dict[str, dict[str, list[str]]]:
    by_id: dict[str, list[str]] = {}
    by_cwe: dict[str, set[str]] = defaultdict(set)
    by_product: dict[str, set[str]] = defaultdict(set)
    by_keyword: dict[str, set[str]] = defaultdict(set)
    by_kev: dict[str, set[str]] = defaultdict(set)
    for record in records:
        by_id[record.cve_id] = [record.cve_id]
        if record.kev:
            by_kev["true"].add(record.cve_id)
        for cwe in record.cwes:
            by_cwe[cwe.upper()].add(record.cve_id)
        for product in record.affected_products:
            by_product[product].add(record.cve_id)
        for token in record.keywords:
            by_keyword[token].add(record.cve_id)
    return {name: {key: sorted(value) for key, value in mapping.items()} for name, mapping in {"by_cwe": by_cwe, "by_product": by_product, "by_keyword": by_keyword, "by_kev": by_kev}.items()} | {"by_id": by_id}


def extract_products(configuration: dict[str, Any]) -> list[str]:
    products: list[str] = []
    for node in configuration.get("nodes", []):
        for match in node.get("cpeMatch", []):
            criteria = str(match.get("criteria") or "")
            product = cpe_to_product(criteria)
            if product:
                products.append(product)
        for child in node.get("children", []):
            products.extend(extract_products({"nodes": [child]}))
    return products


def cpe_to_product(cpe: str) -> str | None:
    parts = cpe.split(":")
    if len(parts) < 5:
        return None
    vendor = parts[3].strip().lower()
    product = parts[4].strip().lower()
    if not vendor or not product or vendor == "*" or product == "*":
        return None
    return f"{vendor}:{product}"


def extract_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in ("cvssMetricV40", "cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
        entries = metrics.get(key) or []
        if not entries:
            continue
        entry = entries[0]
        cvss_data = entry.get("cvssData", {})
        result[key] = {"baseScore": cvss_data.get("baseScore"), "baseSeverity": cvss_data.get("baseSeverity") or entry.get("baseSeverity"), "vectorString": cvss_data.get("vectorString")}
    return result


def tokenize(value: str) -> list[str]:
    return [item.lower() for item in TOKEN_RE.findall(value or "")]


def dedupe_lower(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        cleaned = normalize_domain(value) if "://" in value else value.strip().lower()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            ordered.append(cleaned)
    return ordered


def dedupe_case_sensitive(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        cleaned = value.strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            ordered.append(cleaned)
    return ordered


def _sort_key(record: CVERecord) -> tuple[int, str, str]:
    return (0 if record.kev else 1, record.updated_at or "", record.cve_id)
