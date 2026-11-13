import { FormEvent, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { BrandMark } from "../components/BrandMark";
import { useSession } from "../session";

export function SignUpPage() {
  const { username, ready, signUp } = useSession();
  const [accepted, setAccepted] = useState(false);
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
    const name = String(form.get("username") ?? "");
    const password = String(form.get("password") ?? "");
    const confirm = String(form.get("confirm") ?? "");
    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }
    setError(await signUp(name, password, accepted));
  }

  return (
    <div className="auth">
      <form className="auth-card" onSubmit={onSubmit}>
        <BrandMark large />
        <h1>Create an account</h1>
        <label className="field">
          Username
          <input name="username" autoComplete="username" autoFocus required />
        </label>
        <label className="field">
          Password
          <input name="password" type="password" autoComplete="new-password" minLength={10} required />
        </label>
        <label className="field">
          Confirm password
          <input name="confirm" type="password" autoComplete="new-password" minLength={10} required />
        </label>
        <label className="accept">
          <input
            type="checkbox"
            checked={accepted}
            onChange={(event) => setAccepted(event.target.checked)}
          />
          <span>
            I have read and accept the <Link to="/terms">Terms of Service</Link>.
          </span>
        </label>
        {error ? <p className="form-error">{error}</p> : null}
        <button className="btn btn-primary btn-block" type="submit">
          Sign up
        </button>
        <p className="auth-foot">
          Already have an account? <Link to="/login">Sign in</Link>
        </p>
      </form>
    </div>
  );
}
