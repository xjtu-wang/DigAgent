import React from "react";
import { Download, Eye } from "lucide-react";
import { Badge, Button } from "./ui";

export function EvidenceInline({ evidence, onOpenArtifact }) {
  return (
    <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate font-medium text-slate-900">{evidence.title}</div>
          <div className="mt-0.5 text-[11px] text-slate-500">{evidence.evidence_id}</div>
        </div>
        <Badge>{evidence.type}</Badge>
      </div>
      <p className="mt-2 whitespace-pre-wrap leading-7 text-slate-700">{evidence.summary}</p>
      {evidence.artifacts?.length ? (
        <div className="mt-2 flex flex-wrap gap-2">
          {evidence.artifacts.map((artifact) => (
            <Button key={artifact.artifact_id} variant="secondary" size="sm" onClick={() => onOpenArtifact(artifact.artifact_id)}>
              <Eye size={13} className="mr-1.5" />
              {artifact.kind}
            </Button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function ReportInline({ report, onDownload }) {
  return (
    <div className="mt-3 rounded-xl border border-slate-200 bg-white p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate font-medium text-slate-900">{report.title}</div>
          <div className="mt-0.5 text-[11px] text-slate-500">{report.report_id}</div>
        </div>
        <Badge>{report.kind}</Badge>
      </div>
      <p className="mt-2 whitespace-pre-wrap text-sm leading-7 text-slate-700">{report.summary}</p>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button variant="secondary" size="sm" onClick={() => onDownload(report.report_id, "markdown")}>
          <Download size={13} className="mr-1.5" />
          Markdown
        </Button>
        <Button variant="secondary" size="sm" onClick={() => onDownload(report.report_id, "pdf")}>
          <Download size={13} className="mr-1.5" />
          PDF
        </Button>
      </div>
    </div>
  );
}

export function renderInlineEvidence(evidenceRefs, evidenceState, onToggleEvidence) {
  return (
    <>
      {evidenceRefs.length ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {evidenceRefs.map((evidenceId) => (
            <button
              key={evidenceId}
              type="button"
              className="inline-flex items-center gap-2 rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700"
              onClick={() => onToggleEvidence(evidenceId)}
            >
              <Eye size={12} />
              {evidenceId}
            </button>
          ))}
        </div>
      ) : null}
      {evidenceRefs.map((evidenceId) => {
        const evidence = evidenceState.items[evidenceId];
        if (!evidenceState.openIds.has(evidenceId) || !evidence) {
          return null;
        }
        return <EvidenceInline key={evidenceId} evidence={evidence} onOpenArtifact={(artifactId) => window.open(`/api/artifacts/${artifactId}/content`, "_blank")} />;
      })}
    </>
  );
}
