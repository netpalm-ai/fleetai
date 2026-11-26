import { FormEvent, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError, request } from "../api/client";
import { BrandMark } from "../components/BrandMark";
import { PASSWORD_REJECTED, acceptablePassword } from "../session";

export function ResetPasswordPage() {
  const [params] = useSearchParams();
  const token = (params.get("token") ?? "").trim();
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(token ? null : "This reset link is invalid.");
  const [pending, setPending] = useState(false);
  const lock = useRef(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const password = String(form.get("password") ?? "");
    const confirm = String(form.get("confirm") ?? "");
    if (!password || !confirm) {
      setError("Enter and confirm a password.");
      return;
    }
    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }
    if (!acceptablePassword(password)) {
      setError(PASSWORD_REJECTED);
      return;
    }
    if (lock.current) {
      return;
    }
    lock.current = true;
    setPending(true);
    setError(null);
    try {
      await request<void>("/auth/password/reset", {
        method: "POST",
        body: JSON.stringify({ token, password }),
      });
      setDone(true);
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 422) {
        setError(PASSWORD_REJECTED);
      } else if (err instanceof ApiError && err.status === 400) {
        setError("This reset link is invalid or expired.");
      } else {
        setError("Reset failed.");
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
              />
            </label>
            <label className="field">
              Confirm password
              <input name="confirm" type="password" autoComplete="new-password" />
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
