import { FormEvent, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, request } from "../api/client";
import { isEmail, TOO_MANY_ATTEMPTS } from "../session";

export function ForgotPasswordPage() {
  const [sent, setSent] = useState(false);
  const [emailError, setEmailError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const lock = useRef(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const emailField = form.elements.namedItem("email");
    const email = String(new FormData(form).get("email") ?? "").trim();
    setEmailError(null);
    if (!email) {
      setEmailError("Enter your email.");
      if (emailField instanceof HTMLElement) {
        emailField.focus();
      }
      return;
    }
    if (!isEmail(email)) {
      setEmailError("Enter a valid email address.");
      if (emailField instanceof HTMLElement) {
        emailField.focus();
      }
      return;
    }
    if (lock.current) {
      return;
    }
    lock.current = true;
    setPending(true);
    try {
      await request<{ sent: boolean }>("/auth/password/forgot", {
        method: "POST",
        body: JSON.stringify({ email }),
      });
      setSent(true);
    } catch (err) {
      setEmailError(err instanceof ApiError && err.status === 429 ? TOO_MANY_ATTEMPTS : "Could not send the reset link. Try again.");
      if (emailField instanceof HTMLElement) {
        emailField.focus();
      }
    } finally {
      lock.current = false;
      setPending(false);
    }
  }

  return (
    <div className="auth">
      <form className="auth-card" onSubmit={(event) => void onSubmit(event)} noValidate>
        <h1>Reset password</h1>
        {sent ? (
          <p>If that email has an account, we sent a link to reset the password.</p>
        ) : (
          <>
            <label className="field">
              Email
              <input
                name="email"
                type="email"
                autoComplete="email"
                inputMode="email"
                autoFocus
                aria-invalid={emailError ? true : undefined}
                aria-describedby={emailError ? "forgot-email-error" : undefined}
              />
              {emailError ? (
                <p className="form-error" id="forgot-email-error" role="alert">
                  {emailError}
                </p>
              ) : null}
            </label>
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
