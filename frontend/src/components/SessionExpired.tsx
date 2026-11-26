import { useEffect, useRef } from "react";

const FOCUSABLE = "button, [href], input, select, textarea";

export function SessionExpired({ onSignIn }: { onSignIn: () => void }) {
  const dialog = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const node = dialog.current;
    const previous = document.activeElement;
    node?.querySelector<HTMLElement>("button")?.focus();

    function onKey(event: KeyboardEvent) {
      if (event.key !== "Tab" || !node) {
        return;
      }
      const items = [...node.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((el) => !el.hasAttribute("disabled"));
      if (items.length === 0) {
        event.preventDefault();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      if (!first || !last) {
        event.preventDefault();
        return;
      }
      const active = document.activeElement;
      if (event.shiftKey && (active === first || !node.contains(active))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (active === last || !node.contains(active))) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      if (previous instanceof HTMLElement) {
        previous.focus();
      }
    };
  }, []);

  return (
    <div className="session-expired">
      <div
        ref={dialog}
        className="auth-card"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="session-expired-title"
      >
        <h1 id="session-expired-title">Session expired</h1>
        <p className="muted">You were signed out after a period of inactivity. Sign in again to continue.</p>
        <button type="button" className="btn btn-primary btn-block" onClick={onSignIn}>
          Sign in
        </button>
      </div>
    </div>
  );
}
