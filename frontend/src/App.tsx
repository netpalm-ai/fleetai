import type { ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { ForgotPasswordPage } from "./pages/ForgotPasswordPage";
import { HomePage } from "./pages/HomePage";
import { LoginPage } from "./pages/LoginPage";
import { ResetPasswordPage } from "./pages/ResetPasswordPage";
import { SettingsPage } from "./pages/SettingsPage";
import { SignUpPage } from "./pages/SignUpPage";
import { TermsPage } from "./pages/TermsPage";
import { TicketsPage } from "./pages/TicketsPage";
import { VerifyPage } from "./pages/VerifyPage";
import { SessionProvider, useSession } from "./session";

function RequireAuth({ children }: { children: ReactNode }) {
  const { ready, username } = useSession();
  if (!ready) {
    return (
      <AppShell>
        <main className="shell shell-app">
          <p className="muted">Loading…</p>
        </main>
      </AppShell>
    );
  }
  if (!username) {
    return <Navigate to="/login" replace />;
  }
  return children;
}

export default function App() {
  return (
    <SessionProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/signup" element={<SignUpPage />} />
          <Route path="/verify" element={<VerifyPage />} />
          <Route path="/forgot" element={<ForgotPasswordPage />} />
          <Route path="/reset" element={<ResetPasswordPage />} />
          <Route path="/terms" element={<TermsPage />} />
          <Route
            path="/tickets"
            element={
              <RequireAuth>
                <TicketsPage />
              </RequireAuth>
            }
          />
          <Route
            path="/connectors"
            element={
              <RequireAuth>
                <SettingsPage />
              </RequireAuth>
            }
          />
          <Route
            path="/settings"
            element={
              <RequireAuth>
                <SettingsPage />
              </RequireAuth>
            }
          />
          <Route path="/settings/connectors" element={<Navigate to="/connectors" replace />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </SessionProvider>
  );
}
