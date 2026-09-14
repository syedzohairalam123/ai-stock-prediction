import { memo } from "react";
import { Link, useNavigate } from "react-router-dom";
import type { Announcement } from "../lib/announcements";
import { AIAnalysisService, eventMeta, fmtAnnDate, fmtAnnRelative, sentimentMeta } from "../lib/announcements";

interface Props {
  ann: Announcement;
}

/**
 * Phase 4 announcement card: source facts (official filing surface) are kept
 * visually and structurally separate from the labeled AI-analysis block.
 * Sentiment uses icon + text + accessible label — never color alone.
 */
function AnnouncementCard({ ann }: Props) {
  const navigate = useNavigate();
  const ev = eventMeta(ann.event);
  const se = sentimentMeta(ann.sentiment);
  const rows = AIAnalysisService.structuredRows(ann.structured, ev.label);
  const tickerOrDash = ann.ticker ?? "—";
  const rel = fmtAnnRelative(ann.published);

  return (
    <article className={`ann-card ann-card-${ann.source}`} aria-label={`${ann.company} announcement: ${ann.title}`}>
      {/* ---- header: company, ticker, date, badges ---- */}
      <header className="ann-card-head">
        <div className="ann-card-id">
          <span className="ann-card-avatar" aria-hidden>{(ann.ticker ?? ann.company).slice(0, 2)}</span>
          <div className="ann-card-co">
            <span className="ann-card-company">{ann.company}</span>
            <span className="ann-card-ticker">{tickerOrDash}</span>
          </div>
        </div>
        <div className="ann-card-when">
          <time dateTime={ann.published} title={ann.published}>{fmtAnnDate(ann.published)}</time>
          {rel && <span className="ann-when-rel">{rel}</span>}
          {ann.source === "simulated" && <span className="ann-src-chip ann-src-sim" title="Synthetic demo record — not a real filing">DEMO</span>}
        </div>
      </header>

      <h3 className="ann-card-title">{ann.title}</h3>

      <div className="ann-card-badges">
        <span className={`ann-badge ann-badge-event`} title={`Event category: ${ev.label}`}>
          <span aria-hidden>{ev.icon}</span> {ev.label}
        </span>
        <span
          className={`ann-badge ann-badge-sent ann-sent-${ann.sentiment.toLowerCase()}`}
          role="img"
          aria-label={se.label}
          title={`AI sentiment: ${se.label}`}
        >
          <span aria-hidden>{se.icon}</span> {ann.sentiment}
        </span>
      </div>

      {/* ---- labeled AI summary (always visibly AI-generated) ---- */}
      <section className="ann-ai" aria-label="AI-generated summary">
        <div className="ann-ai-head">
          <span className="ann-ai-chip">AI SUMMARY</span>
          <span className="ann-ai-engine">{ann.analysis_engine}</span>
        </div>
        {ann.highlights.length > 0 && (
          <ul className="ann-ai-highlights">
            {ann.highlights.map((h, i) => (
              <li key={i}>{h}</li>
            ))}
          </ul>
        )}
        {rows.length > 0 && (
          <dl className="ann-structured">
            {rows.map((r) => (
              <div className="ann-structured-row" key={r.label}>
                <dt>{r.label}</dt>
                <dd>{r.value}</dd>
              </div>
            ))}
          </dl>
        )}
        {rows.length === 0 && ann.highlights.length === 0 && (
          <p className="ann-ai-empty">No extractable facts in this filing — see the original document.</p>
        )}
        <p className="ann-ai-disclaimer">AI-generated analysis — not an official PSX statement.</p>
      </section>

      {/* ---- original filing text (source content, not AI) ---- */}
      <details className="ann-body">
        <summary>Original announcement text</summary>
        <pre className="ann-body-text">{ann.body}</pre>
        <p className="ann-src-note">Source content — reproduced from the announcements feed, not AI-generated.</p>
      </details>

      {/* ---- source links ---- */}
      <footer className="ann-links">
        {ann.pdf_url ? (
          <a className="ann-link" href={ann.pdf_url} target="_blank" rel="noreferrer">View Original PDF</a>
        ) : (
          <span className="ann-link ann-link-disabled" title="Official PDF attachments arrive with the PSX Data Portal integration">Original PDF — n/a</span>
        )}
        {ann.image_url ? (
          <a className="ann-link" href={ann.image_url} target="_blank" rel="noreferrer">View Original Image</a>
        ) : (
          <span className="ann-link ann-link-disabled" title="Scanned filing images arrive with the PSX Data Portal integration">Original Image — n/a</span>
        )}
        <a className="ann-link" href={ann.source_url} target="_blank" rel="noreferrer" title="Open the announcements source">Source ↗</a>
        <Link className="ann-link" to={`/announcements/${ann.id}`} title="Open this announcement's permalink">Permalink</Link>
        {ann.ticker && (
          <button className="ann-link ann-link-btn" onClick={() => navigate(`/stock/${ann.ticker}`)}>
            View Stock →
          </button>
        )}
        {ann.ticker && (
          <Link className="ann-link ann-link-btn" to={`/company?ticker=${encodeURIComponent(ann.ticker)}`}>
            Company Fundamentals →
          </Link>
        )}
      </footer>
    </article>
  );
}

// Memoized: the feed re-renders on every filter keystroke, but each card's
// props only change when the server returns different data.
export default memo(AnnouncementCard);
