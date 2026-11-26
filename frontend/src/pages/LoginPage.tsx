import { FormEvent, useRef, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { BrandMark } from "../components/BrandMark";
import { CODE_REQUIRED, isEmail, useSession } from "../session";

export function LoginPage() {
  const { username, ready, signIn } = useSession();
  const [error, setError] = useState<string | null>(null);
  const [needsCode, setNeedsCode] = useState(false);
  const [pending, setPending] = useState(false);
  const lock = useRef(false);

  if (!ready) {
    return (
      <div className="auth">
        <div className="auth-card">
          <BrandMark large />
          <p className="muted">Loading…</p>
        </div>
      </div>
    );
  }
  if (username) {
    return <Navigate to="/tickets" replace />;
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const email = String(form.get("email") ?? "").trim();
    const password = String(form.get("password") ?? "");
    const code = String(form.get("code") ?? "").trim();
    if (!email || !password) {
      setError("Enter your email and password.");
      return;
    }
    if (!isEmail(email)) {
      setError("Enter a valid email address.");
      return;
    }
    if (needsCode && !code) {
      setError(null);
      return;
    }
    if (lock.current) {
      return;
    }
    lock.current = true;
    setPending(true);
    try {
      const message = await signIn(email, password, code);
      if (message === CODE_REQUIRED) {
        setNeedsCode(true);
        setError(null);
        return;
      }
      setError(message);
    } finally {
      lock.current = false;
      setPending(false);
    }
  }

  return (
    <div className="auth">
      <div className="auth-card">
        <BrandMark large />
        <h1>Sign in</h1>
        <form onSubmit={(event) => void onSubmit(event)} noValidate>
          <label className="field">
            Email
            <input
              name="email"
              type="email"
              autoComplete="username"
              inputMode="email"
              autoFocus
            />
          </label>
          <label className="field">
            Password
            <input
              name="password"
              type="password"
              autoComplete="current-password"
            />
          </label>
          {needsCode ? (
            <>
              <p className="field-help">{CODE_REQUIRED}</p>
              <label className="field">
                Authenticator or recovery code
                <input name="code" inputMode="numeric" autoComplete="one-time-code" autoFocus />
              </label>
            </>
          ) : null}
          {error ? (
            <p className="form-error" role="alert">
              {error}
            </p>
          ) : null}
          <button className="btn btn-primary btn-block" type="submit" disabled={pending}>
            Sign in
          </button>
        </form>
        <p className="auth-foot">
          <Link to="/forgot">Forgot password?</Link>
        </p>
        <p className="auth-foot">
          Build your Fleet? <Link to="/signup">Sign up</Link>
        </p>
      </div>
    </div>
  );
}
