import React from "react";
import { cva } from "class-variance-authority";
import { cn } from "../lib";

const buttonVariants = cva(
  "inline-flex items-center justify-center rounded-full px-4 py-2 text-sm font-medium transition duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--app-border-strong)] disabled:cursor-not-allowed disabled:opacity-50",
  {
    variants: {
      variant: {
        primary: "bg-[color:var(--app-text)] text-white shadow-[var(--app-shadow-soft)] hover:bg-[color:var(--app-accent-strong)]",
        secondary: "bg-[color:var(--app-panel)] text-[color:var(--app-text)] ring-1 ring-[color:var(--app-border)] hover:bg-[color:var(--app-panel-muted)]",
        ghost: "bg-transparent text-[color:var(--app-text-soft)] hover:bg-[color:var(--app-panel-muted)] hover:text-[color:var(--app-text)]",
        danger: "bg-[color:var(--app-danger)] text-white hover:opacity-95",
      },
      size: {
        md: "h-10",
        sm: "h-9 px-3 text-xs",
      },
    },
    defaultVariants: {
      variant: "primary",
      size: "md",
    },
  },
);

export function Button({ className, size, variant, ...props }) {
  return <button className={cn(buttonVariants({ variant, size }), className)} {...props} />;
}

export function Input({ className, ...props }) {
  return (
    <input
      className={cn(
        "w-full rounded-[1.35rem] border border-[color:var(--app-border)] bg-[color:var(--app-panel)] px-4 py-3 text-sm text-[color:var(--app-text)] outline-none transition placeholder:text-[color:var(--app-text-faint)] focus:border-[color:var(--app-border-strong)] focus:ring-2 focus:ring-[color:var(--app-panel-strong)]",
        className,
      )}
      {...props}
    />
  );
}

export function Textarea({ className, ...props }) {
  return (
    <textarea
      className={cn(
        "w-full rounded-[1.75rem] border border-[color:var(--app-border)] bg-[color:var(--app-panel)] px-4 py-4 text-sm text-[color:var(--app-text)] outline-none transition placeholder:text-[color:var(--app-text-faint)] focus:border-[color:var(--app-border-strong)] focus:ring-2 focus:ring-[color:var(--app-panel-strong)]",
        className,
      )}
      {...props}
    />
  );
}

export function Badge({ className, children }) {
  return <span className={cn("inline-flex rounded-full bg-[color:var(--app-panel-muted)] px-3 py-1 text-xs font-medium text-[color:var(--app-text-soft)]", className)}>{children}</span>;
}

export function Card({ className, ...props }) {
  return <div className={cn("rounded-[2rem] border border-[color:var(--app-border)] bg-[color:var(--app-panel)] shadow-[var(--app-shadow)]", className)} {...props} />;
}

export function SectionLabel({ className, ...props }) {
  return <div className={cn("text-[11px] font-semibold uppercase tracking-[0.18em] text-[color:var(--app-text-faint)]", className)} {...props} />;
}

export function Toggle({ checked, onChange, label, description }) {
  return (
    <label className="flex items-start justify-between gap-4 rounded-[1.6rem] border border-[color:var(--app-border)] bg-[color:var(--app-panel)] px-4 py-4">
      <div className="min-w-0">
        <div className="text-sm font-medium text-[color:var(--app-text)]">{label}</div>
        {description ? <div className="mt-1 text-sm leading-6 text-[color:var(--app-text-soft)]">{description}</div> : null}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={cn(
          "relative mt-1 inline-flex h-7 w-12 shrink-0 rounded-full transition",
          checked ? "bg-[color:var(--app-text)]" : "bg-[color:var(--app-panel-strong)]",
        )}
      >
        <span
          className={cn(
            "absolute top-1 h-5 w-5 rounded-full bg-white transition",
            checked ? "left-6" : "left-1",
          )}
        />
      </button>
    </label>
  );
}

export function Select({ className, children, ...props }) {
  return (
    <select
      className={cn(
        "w-full rounded-[1.35rem] border border-[color:var(--app-border)] bg-[color:var(--app-panel)] px-4 py-3 text-sm text-[color:var(--app-text)] outline-none transition focus:border-[color:var(--app-border-strong)] focus:ring-2 focus:ring-[color:var(--app-panel-strong)]",
        className,
      )}
      {...props}
    >
      {children}
    </select>
  );
}
