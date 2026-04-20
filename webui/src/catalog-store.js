const EMPTY_CATALOG = Object.freeze({
  profiles: [],
  tools: [],
  skills: [],
  mcp_servers: [],
});

function normalizeArray(value) {
  return Array.isArray(value) ? value : [];
}

export function defaultCatalog() {
  return { ...EMPTY_CATALOG };
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
    mcp_servers: normalizeArray(value.mcp_servers),
  };
}
