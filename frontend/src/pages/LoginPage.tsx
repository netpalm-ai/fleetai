import { FormEvent, useRef, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import {
  CODE_REJECTED,
  CODE_REQUIRED,
  isEmail,
  TOO_MANY_ATTEMPTS,
  useSession,
  VERIFY_EMAIL_FIRST,
} from "../session";

function focusNamed(form: HTMLFormElement, name: string) {
  const field = form.elements.namedItem(name);
  if (field instanceof HTMLElement) {
    field.focus();
  }
}

export function LoginPage() {
  const { username, ready, signIn } = useSession();
  const [emailError, setEmailError] = useState<string | null>(null);
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [codeError, setCodeError] = useState<string | null>(null);
  const [needsCode, setNeedsCode] = useState(false);
  const [pending, setPending] = useState(false);
  const lock = useRef(false);

  if (!ready) {
    return (
      <div className="auth">
        <div className="auth-card">
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
    const form = event.currentTarget;
    const data = new FormData(form);
    const email = String(data.get("email") ?? "").trim();
    const password = String(data.get("password") ?? "");
    const code = String(data.get("code") ?? "").trim();
    setEmailError(null);
    setPasswordError(null);
    setCodeError(null);
    if (!email) {
      setEmailError("Enter your email.");
    } else if (!isEmail(email)) {
      setEmailError("Enter a valid email address.");
    }
    if (!password) {
      setPasswordError("Enter your password.");
    }
    if (needsCode && !code) {
      setCodeError(CODE_REQUIRED);
    }
    if (!email || !isEmail(email) || !password || (needsCode && !code)) {
      if (!email || !isEmail(email)) {
        focusNamed(form, "email");
      } else if (!password) {
        focusNamed(form, "password");
      } else {
        focusNamed(form, "code");
      }
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
        return;
      }
      if (!message) {
        return;
      }
      if (message === CODE_REJECTED) {
        setCodeError(message);
        focusNamed(form, "code");
        return;
      }
      if (message === VERIFY_EMAIL_FIRST || message === TOO_MANY_ATTEMPTS) {
        setEmailError(message);
        focusNamed(form, "email");
        return;
      }
      if (message === "Enter your email and password.") {
        setEmailError("Enter your email.");
        setPasswordError("Enter your password.");
        focusNamed(form, "email");
        return;
      }
      setPasswordError(message);
      focusNamed(form, "password");
    } finally {
      lock.current = false;
      setPending(false);
    }
  }

  return (
    <div className="auth">
      <div className="auth-card">
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
              aria-invalid={emailError ? true : undefined}
              aria-describedby={emailError ? "login-email-error" : undefined}
            />
            {emailError ? (
              <p className="form-error" id="login-email-error" role="alert">
                {emailError}
              </p>
            ) : null}
          </label>
          <label className="field">
            Password
            <input
              name="password"
              type="password"
              autoComplete="current-password"
              aria-invalid={passwordError ? true : undefined}
              aria-describedby={passwordError ? "login-password-error" : undefined}
            />
            {passwordError ? (
              <p className="form-error" id="login-password-error" role="alert">
                {passwordError}
              </p>
            ) : null}
          </label>
          {needsCode ? (
            <>
              <p className="field-help">{CODE_REQUIRED}</p>
              <label className="field">
                Authenticator or recovery code
                <input
                  name="code"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  autoFocus
                  aria-invalid={codeError ? true : undefined}
                  aria-describedby={codeError ? "login-code-error" : undefined}
                />
                {codeError ? (
                  <p className="form-error" id="login-code-error" role="alert">
                    {codeError}
                  </p>
                ) : null}
              </label>
            </>
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
