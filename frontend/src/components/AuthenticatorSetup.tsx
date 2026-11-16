import { useEffect, useState, type FormEvent } from "react";
import { ApiError, request } from "../api/client";

type Setup = { secret: string; qr: string };

function isWrongPassword(err: unknown): boolean {
  return err instanceof ApiError && err.status === 401 && err.message === "invalid credentials";
}

function isLocked(err: unknown): boolean {
  return err instanceof ApiError && err.status === 429;
}

export function AuthenticatorSetup({ onError }: { onError: (err: unknown) => void }) {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [setup, setSetup] = useState<Setup | null>(null);
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    request<{ totp_enabled: boolean }>("/auth/me")
      .then((user) => setEnabled(user.totp_enabled))
      .catch(onError);
  }, [onError]);

  async function onStart() {
    try {
      setSetup(await request<Setup>("/auth/totp/setup", { method: "POST" }));
    } catch (err: unknown) {
      onError(err);
    }
  }

  async function onEnable(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setFormError(null);
    try {
      const result = await request<{ recovery_codes: string[] }>("/auth/totp/enable", {
        method: "POST",
        body: JSON.stringify({
          password: String(form.get("password") ?? ""),
          code: String(form.get("code") ?? "").trim(),
        }),
      });
      setRecoveryCodes(result.recovery_codes);
      setEnabled(true);
      setSetup(null);
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 400) {
        setFormError("That code is wrong.");
        return;
      }
      if (isWrongPassword(err)) {
        setFormError("Wrong password.");
        return;
      }
      onError(err);
    }
  }

  async function onDisable(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setFormError(null);
    try {
      await request<void>("/auth/totp/disable", {
        method: "POST",
        body: JSON.stringify({
          password: String(form.get("password") ?? ""),
          code: String(form.get("code") ?? "").trim(),
        }),
      });
      setEnabled(false);
    } catch (err: unknown) {
      if (isWrongPassword(err)) {
        setFormError("Wrong password or code.");
        return;
      }
      if (isLocked(err)) {
        setFormError("Too many wrong codes. Try again later.");
        return;
      }
      onError(err);
    }
  }

  if (enabled === null) {
    return null;
  }
  return (
    <section className="board settings">
      <div className="board-head">
        <h2>Two-factor authentication</h2>
      </div>
      {recoveryCodes ? (
        <>
          <p className="muted">
            Save these recovery codes now. Each works once if you lose your authenticator app. They are not shown again.
          </p>
          <ul>
            {recoveryCodes.map((code) => (
              <li key={code}>
                <code>{code}</code>
              </li>
            ))}
          </ul>
          <button className="btn btn-primary btn-block" type="button" onClick={() => setRecoveryCodes(null)}>
            I saved them
          </button>
        </>
      ) : null}
      {enabled && !recoveryCodes ? (
        <form onSubmit={(event) => void onDisable(event)} noValidate>
          <p className="muted">On. Signing in asks for a code from your authenticator app.</p>
          <label className="field">
            Password
            <input name="password" type="password" autoComplete="current-password" />
          </label>
          <label className="field">
            Authenticator or recovery code
            <input name="code" inputMode="numeric" autoComplete="one-time-code" />
          </label>
          {formError ? <p className="form-error">{formError}</p> : null}
          <button className="btn btn-primary btn-block" type="submit">
            Turn off
          </button>
        </form>
      ) : null}
      {!enabled && !setup ? (
        <>
          <p className="muted">Off. Add an authenticator app to ask for a code at sign-in.</p>
          <button className="btn btn-primary btn-block" type="button" onClick={() => void onStart()}>
            Set up authenticator
          </button>
        </>
      ) : null}
      {setup ? (
        <form onSubmit={(event) => void onEnable(event)} noValidate>
          <p className="muted">Scan this QR code with your authenticator app, or enter the key {setup.secret}.</p>
          <img src={setup.qr} alt="Authenticator QR code" />
          <label className="field">
            Password
            <input name="password" type="password" autoComplete="current-password" />
          </label>
          <label className="field">
            Code from the app
            <input name="code" inputMode="numeric" autoComplete="one-time-code" />
          </label>
          {formError ? <p className="form-error">{formError}</p> : null}
          <button className="btn btn-primary btn-block" type="submit">
            Turn on
          </button>
        </form>
      ) : null}
    </section>
  );
}
