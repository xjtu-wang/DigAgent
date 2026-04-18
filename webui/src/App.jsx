import React, { useEffect, useState } from "react";
import { useAppRoute } from "./app-router";
import { defaultCatalog, normalizeCatalog } from "./catalog-store";
import { WorkspacePage } from "./components/chat-shell";
import { SettingsPage } from "./components/settings-page";
import { loadAppSettings, resetAppSettings, saveAppSettings } from "./settings-store";
import { useWorkspaceController } from "./use-workspace-controller";

export function App() {
  const { navigate, route } = useAppRoute();
  const [appSettings, setAppSettings] = useState(() => loadAppSettings());
  const [catalog, setCatalog] = useState(() => defaultCatalog());
  const [settingsSummary, setSettingsSummary] = useState(null);
  const controller = useWorkspaceController(appSettings);

  useEffect(() => {
    let cancelled = false;

    async function bootstrap() {
      const [catalogResponse, settingsResponse] = await Promise.all([fetch("/api/catalog"), fetch("/api/settings/summary")]);
      if (cancelled) {
        return;
      }
      if (catalogResponse.ok) {
        setCatalog(normalizeCatalog(await catalogResponse.json()));
      }
      if (settingsResponse.ok) {
        setSettingsSummary(await settingsResponse.json());
      }
    }

    void bootstrap();
    return () => {
      cancelled = true;
    };
  }, []);

  function handleSaveSettings(nextSettings) {
    setAppSettings(saveAppSettings(nextSettings));
  }

  function handleResetSettings() {
    const nextSettings = resetAppSettings();
    setAppSettings(nextSettings);
    return nextSettings;
  }

  if (route === "/settings") {
    return <SettingsPage catalog={catalog} onNavigateHome={() => navigate("/")} onResetSettings={handleResetSettings} onSaveSettings={handleSaveSettings} settings={appSettings} settingsSummary={settingsSummary} />;
  }

  return <WorkspacePage catalog={catalog} controller={controller} onOpenSettings={() => navigate("/settings")} settings={appSettings} />;
}
