import { FormEvent, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError, request } from "../api/client";
import { BrandMark } from "../components/BrandMark";

const MIN_PASSWORD = 12;
const MAX_PASSWORD = 128;
const PASSWORD_RULE = /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9]).{12,128}$/;
const PASSWORD_RULE_TEXT =
  "Use 12 to 128 characters with an uppercase letter, a lowercase letter, a number, and a symbol.";

function acceptablePassword(password: string): boolean {
  return password.length >= MIN_PASSWORD && password.length <= MAX_PASSWORD && PASSWORD_RULE.test(password);
}

export function ResetPasswordPage() {
  const [params] = useSearchParams();
  const token = (params.get("token") ?? "").trim();
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(token ? null : "This reset link is invalid.");

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
      setError(PASSWORD_RULE_TEXT);
      return;
    }
    setError(null);
    try {
      await request<void>("/auth/password/reset", {
        method: "POST",
        body: JSON.stringify({ token, password }),
      });
      setDone(true);
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 422) {
        setError(PASSWORD_RULE_TEXT);
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
              <input
                name="password"
                type="password"
                autoComplete="new-password"
                minLength={MIN_PASSWORD}
                maxLength={MAX_PASSWORD}
                autoFocus
              />
            </label>
            <p className="muted">{PASSWORD_RULE_TEXT}</p>
            <label className="field">
              Confirm password
              <input
                name="confirm"
                type="password"
                autoComplete="new-password"
                minLength={MIN_PASSWORD}
                maxLength={MAX_PASSWORD}
              />
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
