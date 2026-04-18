import React from "react";
import { Download, Eye } from "lucide-react";
import { MarkdownBlock } from "./markdown-block";
import { Badge, Button } from "./ui";

function stringifyValue(value) {
  if (value == null || value === "") {
    return "";
  }
  if (typeof value === "string") {
    return value;
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export function EvidenceInline({ evidence, onOpenArtifact }) {
  return (
    <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate font-medium text-slate-900" title={evidence.title}>{evidence.title}</div>
          <div className="mt-0.5 text-[11px] text-slate-500">{evidence.evidence_id}</div>
        </div>
        <Badge>{evidence.type}</Badge>
      </div>
      <MarkdownBlock className="mt-2" content={evidence.summary} />
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
  const reportBody = report.markdown || report.summary;
  return (
    <div className="mt-3 rounded-xl border border-slate-200 bg-white p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate font-medium text-slate-900" title={report.title}>{report.title}</div>
          <div className="mt-0.5 text-[11px] text-slate-500">{report.report_id}</div>
        </div>
        <Badge>{report.kind}</Badge>
      </div>
      <MarkdownBlock className="mt-2" content={reportBody} />
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

export function FactGrid({ facts }) {
  const items = Array.isArray(facts)
    ? facts
      .map((fact) => {
        if (typeof fact === "string") {
          return { label: "事实", value: fact };
        }
        if (fact && typeof fact === "object") {
          return { label: fact.key || fact.label || "事实", value: stringifyValue(fact.value) };
        }
        return null;
      })
      .filter((item) => item?.value)
    : [];
  if (!items.length) {
    return null;
  }
  return (
    <div className="mt-3 grid gap-2 sm:grid-cols-2">
      {items.map((item, index) => (
        <div key={`${item.label}-${index}`} className="rounded-xl border border-slate-200 bg-white px-3 py-2.5">
          <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">{item.label}</div>
          <div className="mt-1 text-sm leading-6 text-slate-700 [overflow-wrap:anywhere]">{item.value}</div>
        </div>
      ))}
    </div>
  );
}

export function CollapsibleSection({ code = false, content, label }) {
  if (!content) {
    return null;
  }
  return (
    <details className="rounded-xl border border-slate-200 bg-white px-3 py-2.5">
      <summary className="cursor-pointer list-none text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">{label}</summary>
      {code ? <pre className="mt-2 overflow-x-auto whitespace-pre-wrap rounded-xl bg-slate-950 px-3 py-2.5 text-xs leading-6 text-slate-100">{content}</pre> : <MarkdownBlock className="mt-2" content={content} />}
    </details>
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
