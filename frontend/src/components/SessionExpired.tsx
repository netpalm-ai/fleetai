export function SessionExpired({ onSignIn }: { onSignIn: () => void }) {
  return (
    <div className="session-expired">
      <div className="auth-card" role="alertdialog" aria-modal="true" aria-labelledby="session-expired-title">
        <h1 id="session-expired-title">Session expired</h1>
        <p className="muted">You were signed out after a period of inactivity. Sign in again to continue.</p>
        <button type="button" className="btn btn-primary btn-block" onClick={onSignIn} autoFocus>
          Sign in
        </button>
      </div>
    </div>
  );
}
