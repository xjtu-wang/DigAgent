from __future__ import annotations

from digagent.models import Finding, ReportDossier, ReportDraft
from digagent.utils import new_id

ALLOWED_REPORT_KINDS = {"writeup", "pentest_report", "code_review_report", "analysis_note"}


class ReportValidationError(RuntimeError):
    pass


class ReportValidator:
    def validate(self, draft: ReportDraft, dossier: ReportDossier) -> ReportDraft:
        valid_refs = {item["evidence_id"] for item in dossier.evidence if item.get("evidence_id")}
        if not valid_refs:
            raise ReportValidationError("report draft requires evidence-backed dossier")
        if draft.kind not in self._candidate_kinds(dossier):
            raise ReportValidationError(f"report kind '{draft.kind}' is inconsistent with task intent and evidence")
        findings = [self._validate_finding(finding, valid_refs) for finding in draft.findings]
        if not draft.summary.strip():
            raise ReportValidationError("report summary must not be empty")
        if self._summary_conflicts_with_goal(draft.summary, dossier):
            raise ReportValidationError("report summary conflicts with the user goal")
        evidence_refs = [ref for ref in draft.evidence_refs if ref in valid_refs]
        if not evidence_refs:
            raise ReportValidationError("report draft must cite evidence_refs")
        return ReportDraft(
            kind=draft.kind,
            title=draft.title,
            summary=draft.summary,
            findings=findings,
            limitations=draft.limitations,
            writer_summary=draft.writer_summary,
            evidence_refs=evidence_refs,
        )

    def _candidate_kinds(self, dossier: ReportDossier) -> set[str]:
        labels = set((dossier.intent_profile.labels if dossier.intent_profile else []) or [])
        evidence_types = set(dossier.source_evidence_types)
        candidates = {"analysis_note"}
        if "ctf" in labels or "subagent_result" in evidence_types:
            candidates.add("writeup")
        if "web" in labels:
            candidates.add("pentest_report")
        if "code_review" in labels:
            candidates.add("code_review_report")
        hint = dossier.intent_profile.report_kind_hint if dossier.intent_profile else None
        if hint:
            candidates.add(hint)
        return candidates & ALLOWED_REPORT_KINDS

    def _validate_finding(self, finding: Finding, valid_refs: set[str]) -> Finding:
        refs = [ref for ref in finding.evidence_refs if ref in valid_refs]
        if not refs:
            raise ReportValidationError(f"finding '{finding.title}' is missing valid evidence_refs")
        return Finding(
            finding_id=finding.finding_id or new_id("fd"),
            title=finding.title,
            severity=finding.severity,
            confidence=finding.confidence,
            claim=finding.claim,
            evidence_refs=refs,
            reproduction_steps=finding.reproduction_steps,
            remediation=finding.remediation,
        )

    def _summary_conflicts_with_goal(self, summary: str, dossier: ReportDossier) -> bool:
        labels = set((dossier.intent_profile.labels if dossier.intent_profile else []) or [])
        lowered = summary.lower()
        if "ctf" in labels and any(marker in lowered for marker in {"源码分析", "source code review", "code review"}):
            return True
        if "code_review" in labels and "最终 flag" in summary:
            return True
        return False
