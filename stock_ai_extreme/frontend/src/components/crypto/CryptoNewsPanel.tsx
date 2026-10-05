/**
 * Crypto news panel (additive).
 *
 * Real, keyless headlines from Google News RSS for the selected asset — through
 * the same feed pipeline the rest of the app uses. Every entry is attributed to
 * its publisher and linked to its source; a feed that is empty or failed says so
 * (`NO DATA AVAILABLE` / the real reason) rather than being padded with
 * placeholder stories. Freshness is derived from the article's own timestamp,
 * so a stale headline is never dressed up as live (spec §2/§15/§25).
 */
import type { CryptoNewsResponse } from "../../lib/crypto";
import { NA, formatDateTime, relTime, statusTone } from "../../lib/cryptoFormat";
import { CryptoEmpty, CryptoPanel, CryptoWidgetError, CryptoSkeleton } from "./CryptoStates";

export interface CryptoNewsPanelProps {
  symbol: string;
  data: CryptoNewsResponse | undefined;
  loading: boolean;
  error: string | null;
  onRetry?: () => void;
}

export function CryptoNewsPanel({ symbol, data, loading, error, onRetry }: CryptoNewsPanelProps) {
  const articles = data?.articles ?? [];
  const available = data?.status === "OK" && articles.length > 0;

  const badge = data ? (
    <span className="crypto-chip">google-news · {data.count}</span>
  ) : null;

  return (
    <CryptoPanel title={`Live news · ${symbol}`} badge={badge}>
      {error ? (
        <CryptoWidgetError title="NEWS UNAVAILABLE" message={error} onRetry={onRetry} />
      ) : loading && !data ? (
        <CryptoSkeleton height={180} label="Loading live news" />
      ) : !available ? (
        <CryptoEmpty
          title={data?.status === "EMPTY" ? "NO VERIFIED DATA" : "NEWS UNAVAILABLE"}
          reason={data?.reason ?? "The news source returned no usable headlines for this asset."}
          hint="No story is ever invented to fill this panel — only real, attributed headlines appear here."
        />
      ) : (
        <>
          <ul className="crypto-news-list">
            {articles.map((article) => (
              <li key={article.url} className="crypto-news-item">
                <div className="crypto-news-meta">
                  <span className="crypto-news-publisher">{article.publisher}</span>
                  <span className={`freshness ${statusTone(article.data_mode)}`}>{article.data_mode}</span>
                  <span className="dim" title={article.published_at ? formatDateTime(article.published_at) : undefined}>
                    {article.published_at ? relTime(article.published_at) : NA}
                  </span>
                </div>
                <a
                  className="crypto-news-title"
                  href={article.url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {article.title}
                </a>
              </li>
            ))}
          </ul>
          <footer className="crypto-news-foot dim">
            <span>
              Source {data?.source ?? "google-news"} · received{" "}
              {data?.feed?.fetched_at ? formatDateTime(data.feed.fetched_at) : NA}
            </span>
            <span>
              {data?.note ??
                "Real headlines only; sentiment and summaries are not generated in this panel."}
            </span>
          </footer>
        </>
      )}
    </CryptoPanel>
  );
}

export default CryptoNewsPanel;
