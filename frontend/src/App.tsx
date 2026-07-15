import { Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { LandingPage } from "./pages/LandingPage";
import { LoginPage } from "./pages/LoginPage";
import { DashboardPage } from "./pages/DashboardPage";
import { ClientsPage } from "./pages/ClientsPage";
import { ActivityPage } from "./pages/ActivityPage";
import { ProfilePage } from "./pages/ProfilePage";
import { PreferencesPage } from "./pages/PreferencesPage";
import { ProjectWorkspacePage } from "./pages/ProjectWorkspacePage";
import { PublicMapPage } from "./pages/PublicMapPage";
import { ClientPortalPage } from "./pages/ClientPortalPage";
import { AdminPage } from "./pages/AdminPage";
import { NotFoundPage } from "./pages/NotFoundPage";

export function App() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/entrar" element={<LoginPage />} />
      <Route path="/cliente" element={<ClientPortalPage />} />
      <Route path="/mapas/:slug" element={<PublicMapPage />} />
      <Route path="/app" element={<AppShell />}>
        <Route index element={<DashboardPage />} />
        <Route path="clientes" element={<ClientsPage />} />
        <Route path="atividade" element={<ActivityPage />} />
        <Route path="perfil" element={<ProfilePage />} />
        <Route path="preferencias" element={<PreferencesPage />} />
        <Route path="admin" element={<AdminPage />} />
        <Route path="projetos/:projectId" element={<ProjectWorkspacePage />} />
      </Route>
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
