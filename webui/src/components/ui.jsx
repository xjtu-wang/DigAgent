import React from "react";
import { cva } from "class-variance-authority";
import { cn } from "../lib";

const buttonVariants = cva(
  "inline-flex items-center justify-center rounded-2xl px-4 py-2 text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-300 disabled:cursor-not-allowed disabled:opacity-50",
  {
    variants: {
      variant: {
        primary: "bg-slate-900 text-white hover:bg-slate-800",
        secondary: "bg-white text-slate-800 ring-1 ring-slate-200 hover:bg-slate-50",
        ghost: "bg-transparent text-slate-600 hover:bg-slate-100 hover:text-slate-900",
        danger: "bg-rose-600 text-white hover:bg-rose-700",
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
        "w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-slate-400 focus:ring-2 focus:ring-slate-200",
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
        "w-full rounded-[1.75rem] border border-slate-200 bg-white px-4 py-4 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-slate-400 focus:ring-2 focus:ring-slate-200",
        className,
      )}
      {...props}
    />
  );
}

export function Badge({ className, children }) {
  return <span className={cn("inline-flex rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700", className)}>{children}</span>;
}

export function Card({ className, ...props }) {
  return <div className={cn("rounded-[2rem] border border-slate-200 bg-white shadow-[0_16px_50px_rgba(15,23,42,0.06)]", className)} {...props} />;
}

export function SectionLabel({ className, ...props }) {
  return <div className={cn("text-xs font-semibold uppercase tracking-[0.18em] text-slate-400", className)} {...props} />;
}

export function Toggle({ checked, onChange, label, description }) {
  return (
    <label className="flex items-start justify-between gap-4 rounded-3xl border border-slate-200 bg-white px-4 py-4">
      <div className="min-w-0">
        <div className="text-sm font-medium text-slate-900">{label}</div>
        {description ? <div className="mt-1 text-sm leading-6 text-slate-500">{description}</div> : null}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={cn(
          "relative mt-1 inline-flex h-7 w-12 shrink-0 rounded-full transition",
          checked ? "bg-slate-900" : "bg-slate-200",
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
        "w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-200",
        className,
      )}
      {...props}
    >
      {children}
    </select>
  );
}
