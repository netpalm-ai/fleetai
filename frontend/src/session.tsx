import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { SessionExpired } from "./components/SessionExpired";
import { ApiError, request } from "./api/client";

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const MAX_EMAIL = 254;
const MIN_PASSWORD = 10;
const MAX_PASSWORD = 128;
const PING_MS = 5 * 60_000;
const ACTIVITY_EVENTS = ["pointerdown", "pointermove", "keydown", "wheel", "touchstart"];

type AuthUser = {
  id: string;
  username: string;
  email: string;
  first_name: string;
  last_name: string;
  status: string;
  last_signed_in_ts: string | null;
  subscription_status: string;
  registered_product: string;
  features: string[];
  idle_limit_minutes: number;
};

type SessionValue = {
  username: string | null;
  ready: boolean;
  signIn: (email: string, password: string) => Promise<string | null>;
  signUp: (
    firstName: string,
    lastName: string,
    username: string,
    email: string,
    password: string,
    tosAccepted: boolean,
  ) => Promise<string | null>;
  signOut: () => Promise<void>;
  expire: () => void;
};

const SessionContext = createContext<SessionValue | null>(null);

export function isEmail(value: string): boolean {
  return EMAIL.test(value) && value.length <= MAX_EMAIL;
}

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    if (err.status === 409) {
      return "That account already exists.";
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
  const [idleMinutes, setIdleMinutes] = useState<number | null>(null);
  const [expired, setExpired] = useState(false);

  useEffect(() => {
    request<AuthUser>("/auth/me")
      .then((user) => {
        setUsername(user.username);
        setIdleMinutes(user.idle_limit_minutes);
      })
      .catch(() => setUsername(null))
      .finally(() => setReady(true));
  }, []);

  useEffect(() => {
    if (!username || expired || idleMinutes === null) {
      return;
    }
    let lastPing = Date.now();
    let timer = window.setTimeout(lapse, idleMinutes * 60_000);

    function lapse() {
      void request<void>("/auth/logout", { method: "POST" }).catch(() => undefined);
      setExpired(true);
    }

    function onActivity() {
      window.clearTimeout(timer);
      timer = window.setTimeout(lapse, (idleMinutes ?? 0) * 60_000);
      if (Date.now() - lastPing >= PING_MS) {
        lastPing = Date.now();
        request<AuthUser>("/auth/me").catch((err: unknown) => {
          if (err instanceof ApiError && err.status === 401) {
            setExpired(true);
          }
        });
      }
    }

    ACTIVITY_EVENTS.forEach((name) => window.addEventListener(name, onActivity, { passive: true }));
    return () => {
      window.clearTimeout(timer);
      ACTIVITY_EVENTS.forEach((name) => window.removeEventListener(name, onActivity));
    };
  }, [username, expired, idleMinutes]);

  const value = useMemo<SessionValue>(
    () => ({
      username,
      ready,
      async signIn(rawEmail: string, password: string) {
        const name = rawEmail.trim();
        try {
          const user = await request<AuthUser>("/auth/login", {
            method: "POST",
            body: JSON.stringify({ email: name, password }),
          });
          setUsername(user.username);
          setIdleMinutes(user.idle_limit_minutes);
          setExpired(false);
          return null;
        } catch (err) {
          if (err instanceof ApiError && (err.status === 401 || err.status === 403 || err.status === 422)) {
            return "invalid credentials";
          }
          return "Sign in failed.";
        }
      },
      async signUp(
        rawFirst: string,
        rawLast: string,
        rawUsername: string,
        rawEmail: string,
        password: string,
        tosAccepted: boolean,
      ) {
        const firstName = rawFirst.trim();
        const lastName = rawLast.trim();
        const handle = rawUsername.trim();
        const name = rawEmail.trim();
        if (!firstName || !lastName) {
          return "Enter a first and last name.";
        }
        if (!handle) {
          return "Enter a username.";
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
              username: handle,
              email: name,
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
        setExpired(false);
      },
      expire() {
        setExpired(true);
      },
    }),
    [username, ready],
  );

  return (
    <SessionContext.Provider value={value}>
      {children}
      {username && expired ? (
        <SessionExpired
          onSignIn={() => {
            setUsername(null);
            setExpired(false);
          }}
        />
      ) : null}
    </SessionContext.Provider>
  );
}

export function useSession(): SessionValue {
  const value = useContext(SessionContext);
  if (!value) {
    throw new Error("useSession requires SessionProvider");
  }
  return value;
}
