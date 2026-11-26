import { useEffect, useState, type FormEvent } from "react";
import { ApiError, request } from "../api/client";

type Setup = { secret: string; qr: string };

function isWrongPassword(err: unknown): boolean {
  return err instanceof ApiError && err.status === 401 && err.message === "invalid credentials";
}

function isLocked(err: unknown): boolean {
  return err instanceof ApiError && err.status === 429;
}

function focusNamed(form: HTMLFormElement, name: string) {
  const field = form.elements.namedItem(name);
  if (field instanceof HTMLElement) {
    field.focus();
  }
}

export function AuthenticatorSetup({ onError }: { onError: (err: unknown) => void }) {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [setup, setSetup] = useState<Setup | null>(null);
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null);
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [codeError, setCodeError] = useState<string | null>(null);

  useEffect(() => {
    request<{ totp_enabled: boolean }>("/auth/me")
      .then((user) => setEnabled(user.totp_enabled))
      .catch((err: unknown) => {
        onError(err);
        setLoadFailed(true);
      });
  }, [onError]);

  async function onStart() {
    try {
      setSetup(await request<Setup>("/auth/totp/setup", { method: "POST" }));
    } catch (err: unknown) {
      onError(err);
    }
  }

  function readValidatedFields(form: HTMLFormElement): { password: string; code: string } | null {
    const data = new FormData(form);
    const password = String(data.get("password") ?? "");
    const code = String(data.get("code") ?? "").trim();
    setPasswordError(null);
    setCodeError(null);
    if (!password) {
      setPasswordError("Enter your password.");
    }
    if (!code) {
      setCodeError("Enter the authenticator or recovery code.");
    }
    if (!password || !code) {
      focusNamed(form, password ? "code" : "password");
      return null;
    }
    return { password, code };
  }

  async function onEnable(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const fields = readValidatedFields(form);
    if (!fields) {
      return;
    }
    const { password, code } = fields;
    try {
      const result = await request<{ recovery_codes: string[] }>("/auth/totp/enable", {
        method: "POST",
        body: JSON.stringify({ password, code }),
      });
      setRecoveryCodes(result.recovery_codes);
      setEnabled(true);
      setSetup(null);
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 400) {
        setCodeError("That code is wrong.");
        focusNamed(form, "code");
        return;
      }
      if (isWrongPassword(err)) {
        setPasswordError("Wrong password.");
        focusNamed(form, "password");
        return;
      }
      onError(err);
    }
  }

  async function onDisable(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const fields = readValidatedFields(form);
    if (!fields) {
      return;
    }
    const { password, code } = fields;
    try {
      await request<void>("/auth/totp/disable", {
        method: "POST",
        body: JSON.stringify({ password, code }),
      });
      setEnabled(false);
    } catch (err: unknown) {
      if (isWrongPassword(err)) {
        setPasswordError("Wrong password or code.");
        setCodeError("Wrong password or code.");
        focusNamed(form, "password");
        return;
      }
      if (isLocked(err)) {
        setCodeError("Too many wrong codes. Try again later.");
        focusNamed(form, "code");
        return;
      }
      onError(err);
    }
  }

  if (enabled === null) {
    return (
      <section className="board settings">
        <div className="board-head">
          <h2>Two-factor authentication</h2>
        </div>
        <p className="muted">{loadFailed ? "Could not load authenticator settings." : "Loading authenticator…"}</p>
      </section>
    );
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
          <p className="muted">Two-factor authentication is on. Sign-in asks for a code from your authenticator app.</p>
          <label className="field">
            Password
            <input
              name="password"
              type="password"
              autoComplete="current-password"
              aria-invalid={passwordError ? true : undefined}
              aria-describedby={passwordError ? "totp-password-error" : undefined}
            />
            {passwordError ? (
              <p className="form-error" id="totp-password-error" role="alert">
                {passwordError}
              </p>
            ) : null}
          </label>
          <label className="field">
            Authenticator or recovery code
            <input
              name="code"
              inputMode="numeric"
              autoComplete="one-time-code"
              aria-invalid={codeError ? true : undefined}
              aria-describedby={codeError ? "totp-code-error" : undefined}
            />
            {codeError ? (
              <p className="form-error" id="totp-code-error" role="alert">
                {codeError}
              </p>
            ) : null}
          </label>
          <button className="btn btn-primary btn-block" type="submit">
            Turn off
          </button>
        </form>
      ) : null}
      {!enabled && !setup ? (
        <>
          <p className="muted">Two-factor authentication is off. Add an authenticator app to require a code at sign-in.</p>
          <button className="btn btn-primary btn-block" type="button" onClick={() => void onStart()}>
            Set up authenticator
          </button>
        </>
      ) : null}
      {setup ? (
        <form onSubmit={(event) => void onEnable(event)} noValidate>
          <p className="muted">Scan this QR code with your authenticator app, or enter the key {setup.secret}.</p>
          {setup.qr.startsWith("data:image/png") ? <img src={setup.qr} alt="Authenticator QR code" /> : null}
          <label className="field">
            Password
            <input
              name="password"
              type="password"
              autoComplete="current-password"
              aria-invalid={passwordError ? true : undefined}
              aria-describedby={passwordError ? "totp-enable-password-error" : undefined}
            />
            {passwordError ? (
              <p className="form-error" id="totp-enable-password-error" role="alert">
                {passwordError}
              </p>
            ) : null}
          </label>
          <label className="field">
            Code from the app
            <input
              name="code"
              inputMode="numeric"
              autoComplete="one-time-code"
              aria-invalid={codeError ? true : undefined}
              aria-describedby={codeError ? "totp-enable-code-error" : undefined}
            />
            {codeError ? (
              <p className="form-error" id="totp-enable-code-error" role="alert">
                {codeError}
              </p>
            ) : null}
          </label>
          <button className="btn btn-primary btn-block" type="submit">
            Turn on
          </button>
        </form>
      ) : null}
    </section>
  );
}
