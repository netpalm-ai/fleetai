import { FormEvent, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { BrandMark } from "../components/BrandMark";
import { useSession } from "../session";

export function SignUpPage() {
  const { username, ready, signUp } = useSession();
  const [accepted, setAccepted] = useState(false);
  const [created, setCreated] = useState(false);
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
    const firstName = String(form.get("first_name") ?? "");
    const lastName = String(form.get("last_name") ?? "");
    const name = String(form.get("email") ?? "");
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
    const message = await signUp(firstName, lastName, name, password, accepted);
    if (message) {
      setError(message);
      return;
    }
    setCreated(true);
  }

  if (created) {
    return (
      <div className="auth">
        <div className="auth-card">
          <BrandMark large />
          <h1>Verify your email</h1>
          <p>Account created. Verify your email before you sign in.</p>
          <p className="auth-foot">
            Already verified? <Link to="/login">Sign in</Link>
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="auth">
      <form className="auth-card" onSubmit={onSubmit}>
        <BrandMark large />
        <h1>Create an account</h1>
        <label className="field">
          First name
          <input name="first_name" autoComplete="given-name" autoFocus required maxLength={80} />
        </label>
        <label className="field">
          Last name
          <input name="last_name" autoComplete="family-name" required maxLength={80} />
        </label>
        <label className="field">
          Email
          <input
            name="email"
            type="email"
            autoComplete="email"
            inputMode="email"
            required
            maxLength={254}
          />
        </label>
        <label className="field">
          Password
          <input
            name="password"
            type="password"
            autoComplete="new-password"
            minLength={10}
            maxLength={128}
            required
          />
        </label>
        <label className="field">
          Confirm password
          <input
            name="confirm"
            type="password"
            autoComplete="new-password"
            minLength={10}
            maxLength={128}
            required
          />
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
