import test from "node:test";
import assert from "node:assert/strict";
import { defaultCatalog, normalizeCatalog } from "./catalog-store.js";

test("defaultCatalog exposes arrays expected by UI", () => {
  const catalog = defaultCatalog();
  assert.deepEqual(catalog.profiles, []);
  assert.deepEqual(catalog.tools, []);
  assert.deepEqual(catalog.plugins, []);
  assert.deepEqual(catalog.mcp_servers, []);
  assert.deepEqual(catalog.cve, { status: "idle" });
});

test("normalizeCatalog keeps UI-safe defaults when backend omits profiles", () => {
  const catalog = normalizeCatalog({
    framework: "deepagents",
    skills: ["skill-a"],
    mcp_servers: ["playwright-local"],
  });
  assert.deepEqual(catalog.profiles, []);
  assert.deepEqual(catalog.tools, []);
  assert.deepEqual(catalog.plugins, []);
  assert.deepEqual(catalog.skills, ["skill-a"]);
  assert.deepEqual(catalog.mcp_servers, ["playwright-local"]);
  assert.deepEqual(catalog.cve, { status: "idle" });
});
