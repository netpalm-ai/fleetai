import { FormEvent, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError, request } from "../api/client";
import { BrandMark } from "../components/BrandMark";

export function ResetPasswordPage() {
  const [params] = useSearchParams();
  const token = (params.get("token") ?? "").trim();
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(token ? null : "This reset link is invalid.");

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const password = String(new FormData(event.currentTarget).get("password") ?? "");
    setError(null);
    try {
      await request<void>("/auth/password/reset", {
        method: "POST",
        body: JSON.stringify({ token, password }),
      });
      setDone(true);
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 422) {
        setError("Password must be 10 to 128 characters.");
      } else if (err instanceof ApiError && err.status === 400) {
        setError("This reset link is invalid or expired.");
      } else {
        setError("Reset failed.");
      }
    }
  }

  return (
    <div className="auth">
      <form className="auth-card" onSubmit={onSubmit} noValidate>
        <BrandMark large />
        <h1>Choose a new password</h1>
        {done ? <p>Password changed. You can sign in.</p> : null}
        {token && !done ? (
          <>
            <label className="field">
              New password
              <input name="password" type="password" autoComplete="new-password" autoFocus />
            </label>
            <button className="btn btn-primary btn-block" type="submit">
              Change password
            </button>
          </>
        ) : null}
        {error ? <p className="form-error">{error}</p> : null}
        <p className="auth-foot">
          <Link to="/login">Sign in</Link>
        </p>
      </form>
    </div>
  );
}
