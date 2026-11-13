import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { ApiError, request } from "./api/client";

type AuthUser = {
  id: string;
  username: string;
};

type SessionValue = {
  username: string | null;
  ready: boolean;
  signIn: (username: string, password: string) => Promise<string | null>;
  signUp: (username: string, password: string, tosAccepted: boolean) => Promise<string | null>;
  signOut: () => Promise<void>;
};

const SessionContext = createContext<SessionValue | null>(null);

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    if (err.status === 409) {
      return "That username is already in use. Sign in instead.";
    }
    if (err.status === 401) {
      return "invalid credentials";
    }
    if (err.status === 422) {
      return "Check the username, password, and Terms of Service.";
    }
    return err.message;
  }
  return fallback;
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [username, setUsername] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    request<AuthUser>("/auth/me")
      .then((user) => setUsername(user.username))
      .catch(() => setUsername(null))
      .finally(() => setReady(true));
  }, []);

  const value = useMemo<SessionValue>(
    () => ({
      username,
      ready,
      async signIn(rawName: string, password: string) {
        const name = rawName.trim();
        if (!name || !password) {
          return "Enter a username and password.";
        }
        try {
          const user = await request<AuthUser>("/auth/login", {
            method: "POST",
            body: JSON.stringify({ username: name, password }),
          });
          setUsername(user.username);
          return null;
        } catch (err) {
          return errorMessage(err, "Sign in failed.");
        }
      },
      async signUp(rawName: string, password: string, tosAccepted: boolean) {
        const name = rawName.trim();
        if (!name || !password) {
          return "Enter a username and password.";
        }
        if (!tosAccepted) {
          return "Accept the Terms of Service to create an account.";
        }
        try {
          const user = await request<AuthUser>("/auth/register", {
            method: "POST",
            body: JSON.stringify({ username: name, password, tos_accepted: true }),
          });
          setUsername(user.username);
          return null;
        } catch (err) {
          return errorMessage(err, "Sign up failed.");
        }
      },
      async signOut() {
        try {
          await request<void>("/auth/logout", { method: "POST" });
        } catch {
          /* still clear the local session */
        }
        setUsername(null);
      },
    }),
    [username, ready],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
  const value = useContext(SessionContext);
  if (!value) {
    throw new Error("useSession requires SessionProvider");
  }
  return value;
}
