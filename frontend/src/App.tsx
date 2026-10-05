import { Route, Routes } from "react-router-dom";
import { AppShell, RequirePlatformAdmin } from "./components/AppShell";
import { LandingPage } from "./pages/LandingPage";
import { LoginPage } from "./pages/LoginPage";
import { DashboardPage } from "./pages/DashboardPage";
import { ClientsPage } from "./pages/ClientsPage";
import { ClientDetailPage } from "./pages/ClientDetailPage";
import { ActivityPage } from "./pages/ActivityPage";
import { ProfilePage } from "./pages/ProfilePage";
import { PreferencesPage } from "./pages/PreferencesPage";
import { ProjectWorkspacePage } from "./pages/ProjectWorkspacePage";
import { PublicMapPage } from "./pages/PublicMapPage";
import { ClientPortalPage } from "./pages/ClientPortalPage";
import { AdminPage } from "./pages/AdminPage";
import { IntegrationsPage } from "./pages/IntegrationsPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { isLocalDemoMode } from "./api";
import { AppErrorBoundary } from "./components/AppErrorBoundary";

export function App() {
  return (
    <AppErrorBoundary>
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/entrar" element={<LoginPage />} />
        <Route path="/cliente" element={<ClientPortalPage />} />
        {isLocalDemoMode ? <Route path="/mapas/:slug" element={<PublicMapPage />} /> : null}
        <Route path="/app" element={<AppShell />}>
          <Route index element={<DashboardPage />} />
          <Route path="clientes" element={<ClientsPage />} />
          <Route path="clientes/:organizationId" element={<ClientDetailPage />} />
          <Route path="atividade" element={<ActivityPage />} />
          <Route path="perfil" element={<ProfilePage />} />
          <Route path="preferencias" element={<PreferencesPage />} />
          <Route
            path="admin"
            element={
              <RequirePlatformAdmin>
                <AdminPage />
              </RequirePlatformAdmin>
            }
          />
          <Route path="integracoes" element={<RequirePlatformAdmin strict><IntegrationsPage /></RequirePlatformAdmin>} />
          <Route path="projetos/:projectId" element={<ProjectWorkspacePage />} />
        </Route>
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </AppErrorBoundary>
  );
}
