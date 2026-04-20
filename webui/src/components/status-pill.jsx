import React from "react";
import { statusStyles } from "../chat-utils";
import { statusLabel } from "../ui-copy";

export function StatusPill({ status }) {
  return (
    <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-medium ${statusStyles[status] || "bg-slate-100 text-slate-700"}`}>
      {statusLabel(status)}
    </span>
  );
}
