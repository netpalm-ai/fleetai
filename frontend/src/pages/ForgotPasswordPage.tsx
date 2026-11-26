import { FormEvent, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, request } from "../api/client";
import { BrandMark } from "../components/BrandMark";
import { isEmail, TOO_MANY_ATTEMPTS } from "../session";

export function ForgotPasswordPage() {
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const lock = useRef(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const email = String(new FormData(event.currentTarget).get("email") ?? "").trim();
    if (!email) {
      setError("Enter your email.");
      return;
    }
    if (!isEmail(email)) {
      setError("Enter a valid email address.");
      return;
    }
    if (lock.current) {
      return;
    }
    lock.current = true;
    setPending(true);
    setError(null);
    try {
      await request<{ sent: boolean }>("/auth/password/forgot", {
        method: "POST",
        body: JSON.stringify({ email }),
      });
      setSent(true);
    } catch (err) {
      setError(err instanceof ApiError && err.status === 429 ? TOO_MANY_ATTEMPTS : "Request failed.");
    } finally {
      lock.current = false;
      setPending(false);
    }
  }

  return (
    <div className="auth">
      <form className="auth-card" onSubmit={(event) => void onSubmit(event)} noValidate>
        <BrandMark large />
        <h1>Reset password</h1>
        {sent ? (
          <p>If that email has an account, we sent a link to reset the password.</p>
        ) : (
          <>
            <label className="field">
              Email
              <input name="email" type="email" autoComplete="email" inputMode="email" autoFocus />
            </label>
            {error ? (
              <p className="form-error" role="alert">
                {error}
              </p>
            ) : null}
            <button className="btn btn-primary btn-block" type="submit" disabled={pending}>
              Send reset link
            </button>
          </>
        )}
        <p className="auth-foot">
          <Link to="/login">Sign in</Link>
        </p>
      </form>
    </div>
  );
}
