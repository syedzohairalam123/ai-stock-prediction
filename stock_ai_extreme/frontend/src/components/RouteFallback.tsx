/**
 * Route-level loading fallback (Phase 5).
 *
 * Shown only while a lazily-loaded page chunk is being fetched, so code
 * splitting never leaves a blank screen. Announced to assistive tech and
 * respects reduced-motion via the shared `.route-spinner` CSS.
 */
export default function RouteFallback() {
  return (
    <div className="route-loading" role="status" aria-live="polite">
      <span className="route-spinner" aria-hidden />
      <span>Loading…</span>
    </div>
  );
}
