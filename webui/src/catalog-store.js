const EMPTY_CATALOG = Object.freeze({
  profiles: [],
  tools: [],
  skills: [],
  plugins: [],
  mcp_servers: [],
  cve: { status: "idle" },
});

function normalizeArray(value) {
  return Array.isArray(value) ? value : [];
}

export function defaultCatalog() {
  return {
    ...EMPTY_CATALOG,
    cve: { ...EMPTY_CATALOG.cve },
  };
}

export function normalizeCatalog(value) {
  const defaults = defaultCatalog();
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return defaults;
  }
  return {
    ...defaults,
    ...value,
    profiles: normalizeArray(value.profiles),
    tools: normalizeArray(value.tools),
    skills: normalizeArray(value.skills),
    plugins: normalizeArray(value.plugins),
    mcp_servers: normalizeArray(value.mcp_servers),
    cve: value.cve && typeof value.cve === "object" && !Array.isArray(value.cve)
      ? { ...defaults.cve, ...value.cve }
      : defaults.cve,
  };
}
