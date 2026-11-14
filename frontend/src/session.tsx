import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { ApiError, request } from "./api/client";

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const MAX_EMAIL = 254;
const MIN_PASSWORD = 10;
const MAX_PASSWORD = 128;

type AuthUser = {
  id: string;
  username: string;
  first_name: string;
  last_name: string;
};

type SessionValue = {
  username: string | null;
  ready: boolean;
  signIn: (username: string, password: string) => Promise<string | null>;
  signUp: (
    firstName: string,
    lastName: string,
    username: string,
    password: string,
    tosAccepted: boolean,
  ) => Promise<string | null>;
  signOut: () => Promise<void>;
};

const SessionContext = createContext<SessionValue | null>(null);

export function isEmail(value: string): boolean {
  return EMAIL.test(value) && value.length <= MAX_EMAIL;
}

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    if (err.status === 409) {
      return "That email is already in use. Sign in instead.";
    }
    if (err.status === 401) {
      return "invalid credentials";
    }
    if (err.status === 403) {
      return "Verify your email before signing in.";
    }
    if (err.status === 422) {
      return "Check the name, email, password, and Terms of Service.";
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
          return "Enter an email and password.";
        }
        if (!isEmail(name)) {
          return "Enter a valid email address.";
        }
        if (!password || password.length > MAX_PASSWORD) {
          return "Enter a password.";
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
      async signUp(
        rawFirst: string,
        rawLast: string,
        rawName: string,
        password: string,
        tosAccepted: boolean,
      ) {
        const firstName = rawFirst.trim();
        const lastName = rawLast.trim();
        const name = rawName.trim();
        if (!firstName || !lastName) {
          return "Enter a first and last name.";
        }
        if (!name || !password) {
          return "Enter an email and password.";
        }
        if (!isEmail(name)) {
          return "Enter a valid email address.";
        }
        if (password.length < MIN_PASSWORD || password.length > MAX_PASSWORD) {
          return "Password must be 10 to 128 characters.";
        }
        if (!tosAccepted) {
          return "Accept the Terms of Service to create an account.";
        }
        try {
          await request<AuthUser>("/auth/register", {
            method: "POST",
            body: JSON.stringify({
              username: name,
              first_name: firstName,
              last_name: lastName,
              password,
              tos_accepted: true,
            }),
          });
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
