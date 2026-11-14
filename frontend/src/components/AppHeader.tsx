import { Link } from "react-router-dom";
import { useSession } from "../session";
import { BrandMark } from "./BrandMark";

export function AppHeader() {
  const { username, signOut } = useSession();
  return (
    <header className="site-header">
      <div className="nav nav-wide">
        <Link to="/">
          <BrandMark />
        </Link>
        <div className="nav-end">
          <span className="nav-user">{username}</span>
          <Link to="/settings" className="btn btn-ghost">
            Settings
          </Link>
          <button type="button" className="btn btn-ghost" onClick={() => void signOut()}>
            Sign out
          </button>
        </div>
      </div>
    </header>
  );
}
