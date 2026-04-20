import test from "node:test";
import assert from "node:assert/strict";
import { defaultCatalog, normalizeCatalog } from "./catalog-store.js";

test("defaultCatalog exposes arrays expected by UI", () => {
  const catalog = defaultCatalog();
  assert.deepEqual(catalog.profiles, []);
  assert.deepEqual(catalog.tools, []);
  assert.deepEqual(catalog.skills, []);
  assert.deepEqual(catalog.mcp_servers, []);
});

test("normalizeCatalog keeps UI-safe defaults when backend omits profiles", () => {
  const catalog = normalizeCatalog({
    framework: "deepagents",
    skills: [{ name: "skill-a" }],
    mcp_servers: [{ server_id: "playwright-local" }],
  });
  assert.deepEqual(catalog.profiles, []);
  assert.deepEqual(catalog.tools, []);
  assert.deepEqual(catalog.skills, [{ name: "skill-a" }]);
  assert.deepEqual(catalog.mcp_servers, [{ server_id: "playwright-local" }]);
});
