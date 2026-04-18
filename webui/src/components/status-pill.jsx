import React from "react";
import { statusStyles } from "../chat-utils";

export function StatusPill({ status }) {
  return (
    <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-medium ${statusStyles[status] || "bg-slate-100 text-slate-700"}`}>
      {status ? status.replaceAll("_", " ") : "idle"}
    </span>
  );
}
