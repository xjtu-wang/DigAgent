import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const VARIANT_STYLES = {
  default: "text-sm leading-7 text-slate-700",
  body: "text-[15px] leading-7 text-slate-900",
  muted: "text-sm leading-7 text-slate-600",
};

function heading(level) {
  const Tag = `h${level}`;
  const className = level === 1 ? "text-lg font-semibold text-slate-900" : "text-base font-semibold text-slate-900";
  return function Heading(props) {
    return <Tag className={className} {...props} />;
  };
}

function Code({ children, className = "", ...props }) {
  return (
    <code className={`rounded bg-slate-100 px-1 py-0.5 font-mono text-[0.92em] text-slate-800 [overflow-wrap:anywhere] ${className}`.trim()} {...props}>
      {children}
    </code>
  );
}

const MARKDOWN_COMPONENTS = {
  a(props) {
    return <a className="font-medium text-sky-700 underline decoration-sky-300 underline-offset-2 break-all [overflow-wrap:anywhere] hover:text-sky-800" target="_blank" rel="noreferrer" {...props} />;
  },
  blockquote(props) {
    return <blockquote className="border-l-2 border-slate-200 pl-4 text-slate-600" {...props} />;
  },
  code: Code,
  h1: heading(1),
  h2: heading(2),
  h3: heading(3),
  hr() {
    return <hr className="border-slate-200" />;
  },
  li(props) {
    return <li className="leading-7" {...props} />;
  },
  ol(props) {
    return <ol className="list-decimal space-y-1 pl-5" {...props} />;
  },
  p(props) {
    return <p className="leading-7" {...props} />;
  },
  pre(props) {
    return <pre className="max-w-full overflow-x-auto whitespace-pre-wrap break-words rounded-2xl bg-slate-950 px-4 py-3 text-slate-100 [&_code]:rounded-none [&_code]:bg-transparent [&_code]:p-0 [&_code]:font-mono [&_code]:text-[13px] [&_code]:leading-6 [&_code]:text-slate-100" {...props} />;
  },
  table(props) {
    return (
      <div className="max-w-full overflow-x-auto">
        <table className="min-w-full border-collapse overflow-hidden rounded-xl text-left text-sm" {...props} />
      </div>
    );
  },
  td(props) {
    return <td className="border border-slate-200 px-3 py-2 align-top break-words [overflow-wrap:anywhere]" {...props} />;
  },
  th(props) {
    return <th className="border border-slate-200 bg-slate-50 px-3 py-2 font-medium text-slate-900 break-words [overflow-wrap:anywhere]" {...props} />;
  },
  ul(props) {
    return <ul className="list-disc space-y-1 pl-5" {...props} />;
  },
};

function normalizeContent(content) {
  if (typeof content === "string") {
    return content.trim();
  }
  if (typeof content === "number") {
    return String(content);
  }
  return "";
}

export function MarkdownBlock({ className = "", content, variant = "default" }) {
  const source = normalizeContent(content);
  if (!source) {
    return null;
  }
  const variantClassName = VARIANT_STYLES[variant] || VARIANT_STYLES.default;
  return (
    <div className={`min-w-0 break-words [overflow-wrap:anywhere] [&>*:first-child]:mt-0 [&>*:last-child]:mb-0 [&_a]:break-all [&_a]:[overflow-wrap:anywhere] [&_blockquote]:my-3 [&_code]:break-words [&_h1]:mb-3 [&_h1]:mt-5 [&_h2]:mb-3 [&_h2]:mt-5 [&_h3]:mb-2 [&_h3]:mt-4 [&_hr]:my-4 [&_ol]:my-3 [&_p]:my-0 [&_p+*]:mt-3 [&_pre]:my-3 [&_pre]:max-w-full [&_table]:my-3 [&_ul]:my-3 ${variantClassName} ${className}`}>
      <ReactMarkdown components={MARKDOWN_COMPONENTS} remarkPlugins={[remarkGfm]}>
        {source}
      </ReactMarkdown>
    </div>
  );
}
