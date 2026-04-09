from __future__ import annotations

import asyncio

import pytest

from digagent.models import Scope
from digagent.tools import ToolExecutionResult

from tests.helpers import wait_for_run


def _fixture_cve_payload() -> dict:
    return {
        "resultsPerPage": 2,
        "startIndex": 0,
        "totalResults": 2,
        "format": "NVD_CVE",
        "version": "2.0",
        "timestamp": "2026-04-08T10:00:00.000",
        "vulnerabilities": [
            {
                "cve": {
                    "id": "CVE-2024-0001",
                    "published": "2024-01-01T00:00:00.000",
                    "lastModified": "2024-01-02T00:00:00.000",
                    "descriptions": [{"lang": "en", "value": "OpenSSL buffer overflow in a demo parser."}],
                    "weaknesses": [{"description": [{"lang": "en", "value": "CWE-120"}]}],
                    "references": [{"url": "https://example.com/CVE-2024-0001", "source": "example"}],
                    "metrics": {
                        "cvssMetricV31": [
                            {
                                "cvssData": {
                                    "baseScore": 9.8,
                                    "baseSeverity": "CRITICAL",
                                    "vectorString": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
                                }
                            }
                        ]
                    },
                    "configurations": [
                        {
                            "nodes": [
                                {
                                    "cpeMatch": [
                                        {
                                            "criteria": "cpe:2.3:a:openssl:openssl:3.0.0:*:*:*:*:*:*:*",
                                        }
                                    ]
                                }
                            ]
                        }
                    ],
                }
            },
            {
                "cve": {
                    "id": "CVE-2024-0002",
                    "published": "2024-02-01T00:00:00.000",
                    "lastModified": "2024-02-02T00:00:00.000",
                    "descriptions": [{"lang": "en", "value": "Django improper input validation issue."}],
                    "weaknesses": [{"description": [{"lang": "en", "value": "CWE-20"}]}],
                    "references": [{"url": "https://example.com/CVE-2024-0002", "source": "example"}],
                    "configurations": [
                        {
                            "nodes": [
                                {
                                    "cpeMatch": [
                                        {
                                            "criteria": "cpe:2.3:a:django:django:5.0.0:*:*:*:*:*:*:*",
                                        }
                                    ]
                                }
                            ]
                        }
                    ],
                }
            },
        ],
    }


@pytest.mark.asyncio
async def test_cve_sync_and_search(manager):
    async def fake_fetch_page(*, start_index: int, results_per_page: int) -> dict:
        assert start_index == 0
        assert results_per_page == 2000
        return _fixture_cve_payload()

    manager.cve.fetch_page = fake_fetch_page
    state = await manager.sync_cve(max_records=2)
    assert state["status"] == "completed"
    assert state["normalized_records"] == 2
    assert manager.storage.cve_normalized_path().exists()
    assert manager.storage.cve_index_path("by_id").exists()

    by_id = manager.search_cve(cve_id="CVE-2024-0001")
    assert by_id[0]["cve_id"] == "CVE-2024-0001"

    by_keyword = manager.search_cve(query="openssl")
    assert any(item["cve_id"] == "CVE-2024-0001" for item in by_keyword)

    by_cwe = manager.search_cve(cwe="CWE-20")
    assert by_cwe[0]["cve_id"] == "CVE-2024-0002"


def test_api_graph_evidence_archive_and_approval_token(app, manager):
    async def fake_fetch(arguments):
        return ToolExecutionResult(
            title="Web Fetch: https://fixture.test",
            summary="Fetched fixture.test with status 200 and extracted 2 links.",
            raw_output='{"title":"Fixture Site","status_code":200}',
            structured_facts=[
                {"key": "status_code", "value": 200},
                {"key": "content_type", "value": "text/html"},
                {"key": "title", "value": "Fixture Site"},
            ],
            mime_type="application/json",
            artifact_kind="html",
            source={"tool_name": "web_fetch", "url": "https://fixture.test"},
        )

    manager.tools.web_fetch = fake_fetch

    async def setup_run():
        session = manager.create_session(
            title="api-extensions",
            profile_name="sisyphus-default",
            scope=Scope(allowed_domains=["fixture.test"]),
        )
        _, turn = await manager.handle_message(
            session_id=session.session_id,
            content="请分析 https://fixture.test",
            scope=Scope(allowed_domains=["fixture.test"]),
        )
        paused = await wait_for_run(manager, turn.run_id, statuses={"awaiting_approval", "failed"})
        return session.session_id, turn.run_id, paused.approval_ids[0]

    session_id, run_id, approval_id = asyncio.run(setup_run())
    paths = {route.path for route in app.routes}
    assert "/api/sessions" in paths
    assert "/api/runs/{run_id}/graph" in paths
    assert "/api/evidence/{evidence_id}" in paths
    assert "/api/artifacts/{artifact_id}" in paths
    assert "/api/artifacts/{artifact_id}/content" in paths
    assert "/api/sessions/{session_id}/archive" in paths
    assert "/api/sessions/{session_id}/unarchive" in paths

    session_summaries = manager.list_sessions()
    assert session_summaries[0].session_id == session_id
    assert session_summaries[0].pending_approval_count == 1
    assert session_summaries[0].last_message_preview

    graph_payload = manager.get_run_graph(run_id)
    assert graph_payload["run_id"] == run_id
    assert len(graph_payload["nodes"]) >= 4
    assert graph_payload["edges"]
    assert any(node["status"] == "waiting_approval" for node in graph_payload["nodes"])
    assert graph_payload["blocked_node_ids"]

    with pytest.raises(ValueError):
        asyncio.run(
            manager.approve(
                approval_id,
                approved=True,
                resolver="webui",
                approval_token="sha256:bad",
            )
        )

    approval = manager.storage.load_approval(approval_id)
    token = manager._approval_token_value(approval, approved=True, resolver="webui")
    asyncio.run(
        manager.approve(
            approval_id,
            approved=True,
            resolver="webui",
            approval_token=token,
        )
    )

    completed = asyncio.run(wait_for_run(manager, run_id, statuses={"completed", "failed"}))
    assert completed.status.value == "completed"

    evidence_id = manager.storage.find_run(run_id).evidence_ids[0]
    evidence = manager.get_evidence(evidence_id)
    assert evidence.artifact_refs

    artifact = manager.get_artifact(evidence.artifact_refs[0])
    assert manager.get_artifact_bytes(artifact.artifact_id)

    archived = manager.archive_session(session_id)
    assert archived.status.value == "archived"

    restored = manager.unarchive_session(session_id)
    assert restored.status.value == "idle"
