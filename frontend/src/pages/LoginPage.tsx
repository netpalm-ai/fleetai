import { FormEvent, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { BrandMark } from "../components/BrandMark";
import { useSession } from "../session";

export function LoginPage() {
  const { username, ready, signIn } = useSession();
  const [error, setError] = useState<string | null>(null);

  if (!ready) {
    return null;
  }
  if (username) {
    return <Navigate to="/tickets" replace />;
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setError(await signIn(String(form.get("username") ?? ""), String(form.get("password") ?? "")));
  }

  return (
    <div className="auth">
      <form className="auth-card" onSubmit={onSubmit}>
        <BrandMark large />
        <h1>Sign in</h1>
        <label className="field">
          Username
          <input name="username" autoComplete="username" autoFocus required />
        </label>
        <label className="field">
          Password
          <input name="password" type="password" autoComplete="current-password" minLength={10} required />
        </label>
        {error ? <p className="form-error">{error}</p> : null}
        <button className="btn btn-primary btn-block" type="submit">
          Sign in
        </button>
        <p className="auth-foot">
          No account yet? <Link to="/signup">Sign up</Link>
        </p>
      </form>
    </div>
  );
}
