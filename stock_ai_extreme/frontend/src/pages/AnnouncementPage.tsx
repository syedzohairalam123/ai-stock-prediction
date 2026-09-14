import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import type { AnnouncementDetail } from "../lib/announcements";
import { AnnouncementService } from "../lib/announcements";
import AnnouncementCard from "../components/AnnouncementCard";
import { LoadingSkeletonTable } from "../components/MarketSkeletons";
import BaseButton from "../components/BaseButton";
import EmptyState from "../components/EmptyState";

/**
 * Single-announcement permalink (`/announcements/:id`).
 *
 * The backend resolves the hash id against the live PSX feed first, then the
 * clearly-labelled demo dataset, and 404s honestly when it has rolled off the
 * feed. We render exactly what came back — no placeholder filings.
 */
export default function AnnouncementPage() {
  const { id = "" } = useParams<{ id: string }>();
  const [data, setData] = useState<AnnouncementDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    AnnouncementService.fetchById(id)
      .then((d) => {
        if (alive) setData(d);
      })
      .catch((e: unknown) => {
        if (alive) setError(e instanceof Error ? e.message : "Could not load announcement");
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [id, reloadKey]);

  return (
    <main>
      <div className="psx-page-head">
        <div>
          <p>PSX announcements</p>
          <h1>Announcement</h1>
        </div>
        <Link to="/announcements" className="ann-link">
          ← All announcements
        </Link>
      </div>

      {loading && (
        <div className="ann-list" aria-busy="true">
          <LoadingSkeletonTable rows={4} cols={1} />
        </div>
      )}

      {!loading && error && (
        <div className="market-state market-state-error">
          <strong>Announcement unavailable</strong>
          <span>{error}</span>
          <BaseButton variant="outline" size="sm" onClick={() => setReloadKey((k) => k + 1)}>
            Retry
          </BaseButton>
        </div>
      )}

      {!loading && !error && data && (
        <>
          <p className="ann-disclaimers">
            {data.source_disclaimer} {data.ai_disclaimer}
          </p>
          <div className="ann-list">
            <AnnouncementCard ann={data.item} />
          </div>
        </>
      )}

      {!loading && !error && !data && (
        <EmptyState
          variant="search"
          title="Announcement not found"
          description="This filing is not in the current feed — it may have rolled off the feed window."
        />
      )}
    </main>
  );
}
