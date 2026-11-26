import { Link } from "react-router-dom";
import { BrandMark } from "../components/BrandMark";

const CONNECTIONS = [{ name: "GitHub", use: "Repositories the agents work in." }] as const;

export function HomePage() {
  return (
    <>
      <header className="site-header">
        <div className="nav">
          <Link to="/">
            <BrandMark />
          </Link>
          <Link className="btn btn-primary" to="/login">
            Sign in
          </Link>
        </div>
      </header>
      <main className="shell intro">
        <h1>A Fleet of agents that handle and resolve tickets.</h1>
        <p className="intro-lede">
          FleetAI runs multiple agents on the context you provide. They take a
          ticket, work it against your tools, and resolve it.
        </p>
        <div className="intro-actions">
          <Link className="btn btn-primary" to="/login">
            Sign in
          </Link>
          <Link className="btn btn-ghost" to="/signup">
            Create an account
          </Link>
        </div>
        <section className="connect">
          <h2>Connects to the tools you already use</h2>
          <ul className="connect-grid">
            {CONNECTIONS.map((item) => (
              <li key={item.name}>
                <strong>{item.name}</strong>
                <span>{item.use}</span>
              </li>
            ))}
          </ul>
        </section>
      </main>
    </>
  );
}
