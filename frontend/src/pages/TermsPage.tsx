import { Link } from "react-router-dom";
import { TERMS_SECTIONS, TERMS_TITLE, TERMS_UPDATED } from "../data/termsOfService";

export function TermsPage() {
  return (
    <div className="terms-page">
      <article className="terms-doc">
        <p>
          <Link className="btn btn-primary" to="/signup">
            Back to sign up
          </Link>
        </p>
        <h1>{TERMS_TITLE}</h1>
        <p className="muted">Updated {TERMS_UPDATED}</p>
        {TERMS_SECTIONS.map((section) => (
          <section key={section.heading} className="terms-section">
            <h2>{section.heading}</h2>
            {section.body.map((paragraph) => (
              <p key={paragraph}>{paragraph}</p>
            ))}
          </section>
        ))}
      </article>
    </div>
  );
}
