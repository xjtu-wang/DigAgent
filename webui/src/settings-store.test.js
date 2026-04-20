import test from "node:test";
import assert from "node:assert/strict";
import { loadAppSettings, normalizeAppSettings, parseImportedSettings, saveAppSettings } from "./settings-store.js";

function createMemoryStorage() {
  const state = new Map();
  return {
    getItem(key) {
      return state.has(key) ? state.get(key) : null;
    },
    setItem(key, value) {
      state.set(key, value);
    },
  };
}

test("normalizeAppSettings merges partial payloads with defaults", () => {
  const settings = normalizeAppSettings({
    runtimeDefaults: { profile: "hephaestus-deepworker" },
    chatPreferences: { enterToSend: false },
  });
  assert.equal(settings.runtimeDefaults.profile, "hephaestus-deepworker");
  assert.equal(settings.chatPreferences.enterToSend, false);
  assert.equal(settings.layoutPreferences.inspectorDefaultTab, "workflow");
  assert.equal(settings.layoutPreferences.openInspectorOnTurn, false);
  assert.equal(settings.workflowPreferences.focusActiveOnUpdate, true);
});

test("saveAppSettings and loadAppSettings round-trip through storage", () => {
  const storage = createMemoryStorage();
  saveAppSettings(
    {
      runtimeDefaults: { profile: "report-writer", autoApprove: true },
      layoutPreferences: { sidebarCollapsed: true, openInspectorOnTurn: false },
    },
    storage,
  );
  const loaded = loadAppSettings(storage);
  assert.equal(loaded.runtimeDefaults.profile, "report-writer");
  assert.equal(loaded.runtimeDefaults.autoApprove, true);
  assert.equal(loaded.layoutPreferences.sidebarCollapsed, true);
  assert.equal(loaded.layoutPreferences.openInspectorOnTurn, false);
  assert.equal(loaded.chatPreferences.enterToSend, true);
});

test("parseImportedSettings accepts exported JSON shapes", () => {
  const loaded = parseImportedSettings(JSON.stringify({ graphPreferences: { wheelZoom: false }, layoutPreferences: { inspectorDefaultTab: "graph" } }));
  assert.equal(loaded.workflowPreferences.showEventMetadata, false);
  assert.equal(loaded.layoutPreferences.inspectorDefaultTab, "workflow");
  assert.equal(loaded.runtimeDefaults.profile, "sisyphus-default");
});

test("loadAppSettings rewrites legacy graph settings into workflow settings", () => {
  const storage = createMemoryStorage();
  storage.setItem(
    "digagent:webui:settings:v1",
    JSON.stringify({
      layoutPreferences: { inspectorDefaultTab: "graph" },
      graphPreferences: { fitOnOpen: false, fitOnUpdate: true, wheelZoom: false },
    }),
  );
  const loaded = loadAppSettings(storage);
  assert.equal(loaded.layoutPreferences.inspectorDefaultTab, "workflow");
  assert.equal(loaded.workflowPreferences.focusActiveOnOpen, false);
  assert.equal(loaded.workflowPreferences.focusActiveOnUpdate, true);
  assert.equal(loaded.workflowPreferences.showEventMetadata, false);
  assert.deepEqual(JSON.parse(storage.getItem("digagent:webui:settings:v1")), loaded);
});

test("normalizeAppSettings migrates legacy runs tab and openInspectorOnRun", () => {
  const settings = normalizeAppSettings({
    layoutPreferences: {
      inspectorDefaultTab: "runs",
      openInspectorOnRun: false,
    },
  });
  assert.equal(settings.layoutPreferences.inspectorDefaultTab, "execution");
  assert.equal(settings.layoutPreferences.openInspectorOnTurn, false);
});
