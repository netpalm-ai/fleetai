import { FormEvent, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { BrandMark } from "../components/BrandMark";
import { CODE_REQUIRED, useSession } from "../session";

export function LoginPage() {
  const { username, ready, signIn } = useSession();
  const [error, setError] = useState<string | null>(null);
  const [needsCode, setNeedsCode] = useState(false);

  if (!ready) {
    return null;
  }
  if (username) {
    return <Navigate to="/tickets" replace />;
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const message = await signIn(
      String(form.get("email") ?? ""),
      String(form.get("password") ?? ""),
      String(form.get("code") ?? ""),
    );
    setNeedsCode((needed) => needed || message === CODE_REQUIRED);
    setError(message);
  }

  return (
    <div className="auth">
      <form className="auth-card" onSubmit={onSubmit} noValidate>
        <BrandMark large />
        <h1>Sign in</h1>
        <label className="field">
          Email
          <input
            name="email"
            type="email"
            autoComplete="email"
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
          <label className="field">
            Authenticator or recovery code
            <input name="code" inputMode="numeric" autoComplete="one-time-code" autoFocus />
          </label>
        ) : null}
        {error ? <p className="form-error">{error}</p> : null}
        <button className="btn btn-primary btn-block" type="submit">
          Sign in
        </button>
        <p className="auth-foot">
          <Link to="/forgot">Forgot password?</Link>
        </p>
        <p className="auth-foot">
          No account yet? <Link to="/signup">Sign up</Link>
        </p>
      </form>
    </div>
  );
}
