import { FormEvent, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError, request } from "../api/client";
import { BrandMark } from "../components/BrandMark";
import { PASSWORD_REJECTED, acceptablePassword } from "../session";

export function ResetPasswordPage() {
  const [params] = useSearchParams();
  const token = (params.get("token") ?? "").trim();
  const [done, setDone] = useState(false);
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(token ? null : "This reset link is invalid.");
  const [pending, setPending] = useState(false);
  const lock = useRef(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const passwordField = form.elements.namedItem("password");
    const confirmField = form.elements.namedItem("confirm");
    const data = new FormData(form);
    const password = String(data.get("password") ?? "");
    const confirm = String(data.get("confirm") ?? "");
    setPasswordError(null);
    setConfirmError(null);
    setError(null);
    if (!password) {
      setPasswordError("Enter and confirm a password.");
    }
    if (!confirm) {
      setConfirmError("Enter and confirm a password.");
    }
    if (!password || !confirm) {
      const target = !password ? passwordField : confirmField;
      if (target instanceof HTMLElement) {
        target.focus();
      }
      return;
    }
    if (password !== confirm) {
      setConfirmError("Passwords do not match.");
      if (confirmField instanceof HTMLElement) {
        confirmField.focus();
      }
      return;
    }
    if (!acceptablePassword(password)) {
      setPasswordError(PASSWORD_REJECTED);
      if (passwordField instanceof HTMLElement) {
        passwordField.focus();
      }
      return;
    }
    if (lock.current) {
      return;
    }
    lock.current = true;
    setPending(true);
    try {
      await request<void>("/auth/password/reset", {
        method: "POST",
        body: JSON.stringify({ token, password }),
      });
      setDone(true);
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 422) {
        setPasswordError(PASSWORD_REJECTED);
        if (passwordField instanceof HTMLElement) {
          passwordField.focus();
        }
      } else if (err instanceof ApiError && err.status === 400) {
        setError("This reset link is invalid or expired.");
      } else {
        setError("Could not change the password. Try again.");
      }
    } finally {
      lock.current = false;
      setPending(false);
    }
  }

  return (
    <div className="auth">
      <form className="auth-card" onSubmit={(event) => void onSubmit(event)} noValidate>
        <BrandMark large />
        <h1>Choose a new password</h1>
        {done ? <p>Password changed. You can sign in.</p> : null}
        {token && !done ? (
          <>
            <label className="field">
              New password
              <input
                name="password"
                type="password"
                autoComplete="new-password"
                autoFocus
                aria-invalid={passwordError ? true : undefined}
                aria-describedby={passwordError ? "reset-password-error" : undefined}
              />
              {passwordError ? (
                <p className="form-error" id="reset-password-error" role="alert">
                  {passwordError}
                </p>
              ) : null}
            </label>
            <label className="field">
              Confirm password
              <input
                name="confirm"
                type="password"
                autoComplete="new-password"
                aria-invalid={confirmError ? true : undefined}
                aria-describedby={confirmError ? "reset-confirm-error" : undefined}
              />
              {confirmError ? (
                <p className="form-error" id="reset-confirm-error" role="alert">
                  {confirmError}
                </p>
              ) : null}
            </label>
            <button className="btn btn-primary btn-block" type="submit" disabled={pending}>
              Change password
            </button>
          </>
        ) : null}
        {error ? (
          <p className="form-error" role="alert">
            {error}
          </p>
        ) : null}
        <p className="auth-foot">
          <Link to="/login">Sign in</Link>
        </p>
      </form>
    </div>
  );
}
