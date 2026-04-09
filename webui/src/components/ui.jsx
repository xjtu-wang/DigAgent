import React from "react";
import { cva } from "class-variance-authority";
import { cn } from "../lib";

export function Card({ className, ...props }) {
  return <div className={cn("rounded-3xl border border-slate-200/80 bg-white/90 shadow-panel backdrop-blur", className)} {...props} />;
}

export function CardHeader({ className, ...props }) {
  return <div className={cn("border-b border-slate-200/80 px-6 py-5", className)} {...props} />;
}

export function CardTitle({ className, ...props }) {
  return <h2 className={cn("font-display text-xl font-semibold tracking-tight text-ink", className)} {...props} />;
}

export function CardContent({ className, ...props }) {
  return <div className={cn("px-6 py-5", className)} {...props} />;
}

const buttonVariants = cva(
  "inline-flex items-center justify-center rounded-full px-4 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50",
  {
    variants: {
      variant: {
        primary: "bg-ink text-white hover:bg-slate-800",
        secondary: "bg-white text-ink ring-1 ring-slate-300 hover:bg-slate-50",
        danger: "bg-ember text-white hover:bg-orange-800",
      },
    },
    defaultVariants: {
      variant: "primary",
    },
  },
);

export function Button({ className, variant, ...props }) {
  return <button className={cn(buttonVariants({ variant }), className)} {...props} />;
}

export function Input({ className, ...props }) {
  return (
    <input
      className={cn("w-full rounded-2xl border border-slate-300 bg-white px-4 py-2 text-sm outline-none ring-0 placeholder:text-slate-400 focus:border-sea", className)}
      {...props}
    />
  );
}

export function Textarea({ className, ...props }) {
  return (
    <textarea
      className={cn("min-h-36 w-full rounded-3xl border border-slate-300 bg-white px-4 py-3 text-sm outline-none placeholder:text-slate-400 focus:border-sea", className)}
      {...props}
    />
  );
}

export function Badge({ className, children }) {
  return <span className={cn("inline-flex rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700", className)}>{children}</span>;
}

