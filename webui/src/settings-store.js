const SETTINGS_VERSION = 1;
export const SETTINGS_STORAGE_KEY = `digagent:webui:settings:v${SETTINGS_VERSION}`;

export const DEFAULT_APP_SETTINGS = Object.freeze({
  runtimeDefaults: {
    profile: "sisyphus-default",
    repoPath: "",
    domain: "",
    autoApprove: false,
  },
  chatPreferences: {
    enterToSend: true,
    timelineDensity: "comfortable",
    showKeySystemCards: true,
  },
  layoutPreferences: {
    sidebarCollapsed: false,
    inspectorDefaultTab: "workflow",
    openInspectorOnTurn: true,
  },
  workflowPreferences: {
    focusActiveOnOpen: true,
    focusActiveOnUpdate: true,
    showEventMetadata: true,
    expandDebugDataByDefault: false,
  },
});

function cloneDefaults() {
  return JSON.parse(JSON.stringify(DEFAULT_APP_SETTINGS));
}

function mergeSection(defaults, value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return { ...defaults };
  }
  return { ...defaults, ...value };
}

function normalizeInspectorTab(value) {
  if (value === "graph") {
    return "workflow";
  }
  if (value === "runs") {
    return "execution";
  }
  return value;
}

function migrateWorkflowPreferences(value) {
  if (value?.workflowPreferences && typeof value.workflowPreferences === "object" && !Array.isArray(value.workflowPreferences)) {
    return value.workflowPreferences;
  }
  const legacy = value?.graphPreferences;
  if (!legacy || typeof legacy !== "object" || Array.isArray(legacy)) {
    return null;
  }
  return {
    focusActiveOnOpen: legacy.fitOnOpen ?? true,
    focusActiveOnUpdate: legacy.fitOnUpdate ?? true,
    showEventMetadata: legacy.wheelZoom ?? true,
  };
}

export function normalizeWorkflowPreferences(value) {
  return mergeSection(DEFAULT_APP_SETTINGS.workflowPreferences, value);
}

export function normalizeAppSettings(value) {
  const defaults = cloneDefaults();
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return defaults;
  }
  const layoutPreferences = mergeSection(defaults.layoutPreferences, value.layoutPreferences);
  if (typeof value?.layoutPreferences?.openInspectorOnRun === "boolean" && typeof value?.layoutPreferences?.openInspectorOnTurn !== "boolean") {
    layoutPreferences.openInspectorOnTurn = value.layoutPreferences.openInspectorOnRun;
  }
  layoutPreferences.inspectorDefaultTab = normalizeInspectorTab(layoutPreferences.inspectorDefaultTab) || defaults.layoutPreferences.inspectorDefaultTab;
  return {
    runtimeDefaults: mergeSection(defaults.runtimeDefaults, value.runtimeDefaults),
    chatPreferences: mergeSection(defaults.chatPreferences, value.chatPreferences),
    layoutPreferences,
    workflowPreferences: normalizeWorkflowPreferences(migrateWorkflowPreferences(value) || value.workflowPreferences),
  };
}

export function serializeAppSettings(settings) {
  return JSON.stringify(normalizeAppSettings(settings), null, 2);
}

export function parseImportedSettings(text) {
  return normalizeAppSettings(JSON.parse(text));
}

export function loadAppSettings(storage = globalThis?.localStorage) {
  if (!storage) {
    return cloneDefaults();
  }
  try {
    const rawValue = storage.getItem(SETTINGS_STORAGE_KEY);
    if (!rawValue) {
      return cloneDefaults();
    }
    const normalized = normalizeAppSettings(JSON.parse(rawValue));
    storage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(normalized));
    return normalized;
  } catch {
    return cloneDefaults();
  }
}

export function saveAppSettings(settings, storage = globalThis?.localStorage) {
  const normalized = normalizeAppSettings(settings);
  if (storage) {
    storage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(normalized));
  }
  return normalized;
}

export function resetAppSettings(storage = globalThis?.localStorage) {
  const defaults = cloneDefaults();
  if (storage) {
    storage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(defaults));
  }
  return defaults;
}

export function createRuntimeDraft(settings) {
  const normalized = normalizeAppSettings(settings);
  return {
    profile: normalized.runtimeDefaults.profile,
    repoPath: normalized.runtimeDefaults.repoPath,
    domain: normalized.runtimeDefaults.domain,
    autoApprove: normalized.runtimeDefaults.autoApprove,
  };
}

export function loadWorkflowPreferences(storage = globalThis?.localStorage, fallback = null) {
  const normalized = storage ? loadAppSettings(storage) : normalizeAppSettings({ workflowPreferences: fallback });
  return normalizeWorkflowPreferences(normalized.workflowPreferences || fallback);
}

export function updateWorkflowPreferences(patch, storage = globalThis?.localStorage) {
  const current = storage ? loadAppSettings(storage) : normalizeAppSettings({});
  const next = {
    ...current,
    workflowPreferences: normalizeWorkflowPreferences({ ...current.workflowPreferences, ...patch }),
  };
  return saveAppSettings(next, storage).workflowPreferences;
}
