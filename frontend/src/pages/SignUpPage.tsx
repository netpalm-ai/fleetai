import { FormEvent, useRef, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { BrandMark } from "../components/BrandMark";
import { acceptablePassword, isEmail, PASSWORD_REJECTED, TOO_MANY_ATTEMPTS, useSession } from "../session";

function focusNamed(form: HTMLFormElement, name: string) {
  const field = form.elements.namedItem(name);
  if (field instanceof HTMLElement) {
    field.focus();
  }
}

export function SignUpPage() {
  const { username, ready, signUp } = useSession();
  const [accepted, setAccepted] = useState(false);
  const [created, setCreated] = useState(false);
  const [firstError, setFirstError] = useState<string | null>(null);
  const [lastError, setLastError] = useState<string | null>(null);
  const [usernameError, setUsernameError] = useState<string | null>(null);
  const [emailError, setEmailError] = useState<string | null>(null);
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [tosError, setTosError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const lock = useRef(false);

  if (!ready) {
    return (
      <div className="auth">
        <div className="auth-card">
          <BrandMark large />
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
    const firstName = String(data.get("first_name") ?? "").trim();
    const lastName = String(data.get("last_name") ?? "").trim();
    const handle = String(data.get("username") ?? "").trim();
    const name = String(data.get("email") ?? "").trim();
    const password = String(data.get("password") ?? "");
    const confirm = String(data.get("confirm") ?? "");
    setFirstError(null);
    setLastError(null);
    setUsernameError(null);
    setEmailError(null);
    setPasswordError(null);
    setConfirmError(null);
    setTosError(null);
    if (!firstName) {
      setFirstError("Enter a first name.");
    }
    if (!lastName) {
      setLastError("Enter a last name.");
    }
    if (!handle) {
      setUsernameError("Enter a username.");
    }
    if (!name) {
      setEmailError("Enter an email.");
    } else if (!isEmail(name)) {
      setEmailError("Enter a valid email address.");
    }
    if (!password) {
      setPasswordError("Enter and confirm a password.");
    } else if (!acceptablePassword(password)) {
      setPasswordError(PASSWORD_REJECTED);
    }
    if (!confirm) {
      setConfirmError("Enter and confirm a password.");
    } else if (password && password !== confirm) {
      setConfirmError("Passwords do not match.");
    }
    if (!accepted) {
      setTosError("Accept the Terms of Service to create an account.");
    }
    const invalid =
      !firstName ||
      !lastName ||
      !handle ||
      !name ||
      !isEmail(name) ||
      !password ||
      !confirm ||
      password !== confirm ||
      !acceptablePassword(password) ||
      !accepted;
    if (invalid) {
      if (!firstName) {
        focusNamed(form, "first_name");
      } else if (!lastName) {
        focusNamed(form, "last_name");
      } else if (!handle) {
        focusNamed(form, "username");
      } else if (!name || !isEmail(name)) {
        focusNamed(form, "email");
      } else if (!password || !acceptablePassword(password)) {
        focusNamed(form, "password");
      } else if (!confirm || password !== confirm) {
        focusNamed(form, "confirm");
      }
      return;
    }
    if (lock.current) {
      return;
    }
    lock.current = true;
    setPending(true);
    try {
      const message = await signUp(firstName, lastName, handle, name, password, accepted);
      if (!message) {
        setCreated(true);
        return;
      }
      if (message === "That account already exists.") {
        setUsernameError(message);
        setEmailError(message);
        focusNamed(form, "username");
        return;
      }
      if (message === TOO_MANY_ATTEMPTS) {
        setEmailError(message);
        focusNamed(form, "email");
        return;
      }
      if (message === PASSWORD_REJECTED) {
        setPasswordError(message);
        focusNamed(form, "password");
        return;
      }
      if (message === "Check the name, email, password, and Terms of Service.") {
        setEmailError(message);
        focusNamed(form, "email");
        return;
      }
      setEmailError(message);
      focusNamed(form, "email");
    } finally {
      lock.current = false;
      setPending(false);
    }
  }

  if (created) {
    return (
      <div className="auth">
        <div className="auth-card">
          <BrandMark large />
          <h1>Verify your email</h1>
          <p>Account created. Open the email we sent and follow the link to verify your email.</p>
          <p className="auth-foot">
            Already verified? <Link to="/login">Sign in</Link>
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="auth">
      <form className="auth-card" onSubmit={(event) => void onSubmit(event)} noValidate>
        <BrandMark large />
        <h1>Create an account</h1>
        <label className="field">
          First name
          <input
            name="first_name"
            autoComplete="given-name"
            autoFocus
            required
            maxLength={80}
            aria-invalid={firstError ? true : undefined}
            aria-describedby={firstError ? "signup-first-error" : undefined}
          />
          {firstError ? (
            <p className="form-error" id="signup-first-error" role="alert">
              {firstError}
            </p>
          ) : null}
        </label>
        <label className="field">
          Last name
          <input
            name="last_name"
            autoComplete="family-name"
            required
            maxLength={80}
            aria-invalid={lastError ? true : undefined}
            aria-describedby={lastError ? "signup-last-error" : undefined}
          />
          {lastError ? (
            <p className="form-error" id="signup-last-error" role="alert">
              {lastError}
            </p>
          ) : null}
        </label>
        <label className="field">
          Username
          <input
            name="username"
            autoComplete="username"
            required
            maxLength={80}
            aria-invalid={usernameError ? true : undefined}
            aria-describedby={usernameError ? "signup-username-error" : undefined}
          />
          {usernameError ? (
            <p className="form-error" id="signup-username-error" role="alert">
              {usernameError}
            </p>
          ) : null}
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
            aria-invalid={emailError ? true : undefined}
            aria-describedby={emailError ? "signup-email-error" : undefined}
          />
          {emailError ? (
            <p className="form-error" id="signup-email-error" role="alert">
              {emailError}
            </p>
          ) : null}
        </label>
        <label className="field">
          Password
          <input
            name="password"
            type="password"
            autoComplete="new-password"
            required
            aria-invalid={passwordError ? true : undefined}
            aria-describedby={passwordError ? "signup-password-error" : undefined}
          />
          {passwordError ? (
            <p className="form-error" id="signup-password-error" role="alert">
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
            required
            aria-invalid={confirmError ? true : undefined}
            aria-describedby={confirmError ? "signup-confirm-error" : undefined}
          />
          {confirmError ? (
            <p className="form-error" id="signup-confirm-error" role="alert">
              {confirmError}
            </p>
          ) : null}
        </label>
        <label className="accept">
          <input
            type="checkbox"
            checked={accepted}
            onChange={(event) => setAccepted(event.target.checked)}
            aria-invalid={tosError ? true : undefined}
            aria-describedby={tosError ? "signup-tos-error" : undefined}
          />
          <span>
            I have read and accept the <Link to="/terms">Terms of Service</Link>.
          </span>
        </label>
        {tosError ? (
          <p className="form-error" id="signup-tos-error" role="alert">
            {tosError}
          </p>
        ) : null}
        <button className="btn btn-primary btn-block" type="submit" disabled={pending}>
          Sign up
        </button>
        <p className="auth-foot">
          Already have an account? <Link to="/login">Sign in</Link>
        </p>
      </form>
    </div>
  );
}
