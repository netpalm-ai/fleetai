import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { request } from "../api/client";
import { BrandMark } from "../components/BrandMark";

export function VerifyPage() {
  const [params] = useSearchParams();
  const token = (params.get("token") ?? "").trim();
  const [status, setStatus] = useState<"wait" | "ok" | "bad">(token ? "wait" : "bad");
  const started = useRef(false);

  useEffect(() => {
    if (!token || started.current) {
      return;
    }
    started.current = true;
    request<{ verified: boolean }>("/auth/verify", {
      method: "POST",
      body: JSON.stringify({ token }),
    })
      .then(() => setStatus("ok"))
      .catch(() => setStatus("bad"));
  }, [token]);

  return (
    <div className="auth">
      <div className="auth-card">
        <BrandMark large />
        <h1>Verify email</h1>
        {status === "wait" ? <p className="muted">Confirming your email…</p> : null}
        {status === "ok" ? <p>Email verified. You can sign in.</p> : null}
        {status === "bad" ? (
          <p className="form-error" role="alert">
            This verification link is invalid or expired.
          </p>
        ) : null}
        <p className="auth-foot">
          <Link to="/login">Sign in</Link>
        </p>
      </div>
    </div>
  );
}
