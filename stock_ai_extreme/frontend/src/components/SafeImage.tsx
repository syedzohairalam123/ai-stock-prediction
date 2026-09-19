/**
 * Phase 8 — SafeImage
 *
 * A news image that cannot break the layout or blank the page (spec N).
 *
 * Publishers serve remote images that 404, redirect, time out, return HTML
 * error bodies, or arrive with no dimensions at all. This component handles
 * every one of those cases the same honest way: reserve the box, keep the
 * aspect ratio, show a clearly-labelled fallback, and never leave a broken
 * image icon on screen.
 *
 *  - **Lazy loading** (`loading="lazy"` + `decoding="async"`) so a 40-item feed
 *    does not fetch 40 remote images at once.
 *  - **Aspect-ratio preservation** via a wrapper with a fixed `aspect-ratio`, so
 *    images of any shape fill the slot without causing layout shift (CLS).
 *  - **Fallback + broken-image handling**: `onError` swaps to a neutral
 *    placeholder; a missing `src` never renders an `<img>` at all.
 *  - **Accessible alt text**: callers pass a real description (normally the
 *    headline). The fallback is marked `role="img"` with its own label so a
 *    screen reader never announces "image" with no content.
 *  - **`referrerPolicy="no-referrer"`** plus a **one-shot proxy retry**: several
 *    publisher CDNs answer a cross-origin `<img>` with HTTP 403 because the
 *    Referer header reveals the embedding site. Sending no referrer fixes some
 *    of them; for the rest, the image is retried once through the backend's
 *    allow-listed `/api/news/image` endpoint, which fetches it server-side where
 *    the block does not apply. Only if *that* fails does the placeholder appear.
 */

import { useEffect, useState } from "react";
import { proxiedImageUrl } from "../lib/newsService";

/**
 * Hosts that have already refused both a direct browser load and the backend
 * proxy *in this session*.
 *
 * Some publisher CDNs block cross-origin `<img>` requests outright and reject
 * server requests too, so an article from those hosts can never render a
 * picture. Without this memo, a 40-item feed would re-attempt and re-fail the
 * same blocked host on every render; with it, the host is tried once and then
 * short-circuits straight to the placeholder. Session-scoped on purpose — a
 * CDN's policy can change, and a hardcoded list would never notice.
 */
const blockedHosts = new Set<string>();

/**
 * Hosts measured to refuse the image to *both* the browser and the backend.
 *
 * Distinct from `blockedHosts`: that set is learned at runtime, whereas these
 * were confirmed by hand — `content-media.investing.com` answers a cross-origin
 * `<img>`, a no-referrer request, and the server-side proxy with HTTP 403, so
 * an article from it can never render a picture. Skipping the request entirely
 * avoids a guaranteed failed load (and the 403 the browser logs for one) and
 * goes straight to the labelled placeholder. Kept small on purpose: a host is
 * only added here once direct, proxy and no-referrer have all been observed to
 * fail, because there is no point paying a round trip to learn that again.
 */
const IMAGE_BLOCKED_HOSTS = new Set<string>(["content-media.investing.com"]);

function hostOf(url: string | null | undefined): string {
  if (!url) return "";
  try {
    return new URL(url).hostname.toLowerCase();
  } catch {
    return "";
  }
}

export interface SafeImageProps {
  /** Remote image URL, or null/undefined when the article has no image. */
  src: string | null | undefined;
  /** Required, meaningful alternative text — normally the article headline. */
  alt: string;
  /** CSS class for the `<img>` itself. */
  className?: string;
  /** CSS class for the aspect-ratio wrapper. */
  wrapperClassName?: string;
  /** Intrinsic aspect ratio of the slot, e.g. `"16 / 9"` or `"4 / 3"`. */
  aspectRatio?: string;
  /** `eager` for the hero image, `lazy` (the default) everywhere else. */
  loading?: "lazy" | "eager";
  /** Rendered inside the placeholder box when there is no usable image. */
  fallbackLabel?: string;
  /**
   * Retry a failed direct load through the backend image proxy before falling
   * back to the placeholder. Disable for servers already known to work.
   */
  retryWithProxy?: boolean;
}

/** Neutral inline-SVG placeholder — no network request, no broken icon. */
const PLACEHOLDER_SVG =
  "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='640' height='360'%3E" +
  "%3Crect width='640' height='360' fill='%23111827'/%3E" +
  "%3Cg fill='none' stroke='%234b5563' stroke-width='10' stroke-linecap='round' stroke-linejoin='round'%3E" +
  "%3Crect x='240' y='130' width='160' height='110' rx='10'/%3E" +
  "%3Cpath d='M265 215l35-35 30 30 25-25 30 30'/%3E%3Ccircle cx='285' cy='165' r='10'/%3E" +
  "%3C/g%3E%3C/svg%3E";

export default function SafeImage({
  src,
  alt,
  className = "",
  wrapperClassName = "",
  aspectRatio = "16 / 9",
  loading = "lazy",
  fallbackLabel = "No image available",
  retryWithProxy = true,
}: SafeImageProps) {
  /** 0 = direct URL, 1 = backend proxy, 2 = give up and show the placeholder. */
  const [attempt, setAttempt] = useState(0);

  // A new URL deserves a fresh attempt: without this, switching articles in a
  // recycled component would keep showing the previous article's fallback.
  useEffect(() => {
    setAttempt(0);
  }, [src]);

  const host = hostOf(src);
  const blocked = IMAGE_BLOCKED_HOSTS.has(host) || blockedHosts.has(host);
  const proxied = retryWithProxy ? proxiedImageUrl(src) : null;
  const candidates = (blocked ? [] : [src ?? null, proxied]).filter(Boolean) as string[];
  const activeSrc = candidates[attempt] ?? null;
  const usable = Boolean(activeSrc);

  /** Exhausted every option: remember the host so we stop asking. */
  const handleError = () => {
    setAttempt((current) => {
      const next = current + 1;
      if (next >= candidates.length) {
        const host = hostOf(src);
        if (host) blockedHosts.add(host);
      }
      return next;
    });
  };

  return (
    <div
      className={`safe-image ${wrapperClassName}`.trim()}
      style={{ aspectRatio }}
      data-image-state={usable ? "loaded" : "fallback"}
    >
      {usable ? (
        <img
          key={activeSrc}
          src={activeSrc as string}
          alt={alt}
          className={`safe-image-img ${className}`.trim()}
          loading={loading}
          decoding="async"
          referrerPolicy="no-referrer"
          // Remote publisher images have unknown intrinsic size; the wrapper's
          // aspect-ratio is what actually holds the layout, so the image just
          // fills it.
          onError={handleError}
        />
      ) : (
        <div
          className={`safe-image-fallback ${className}`.trim()}
          role="img"
          aria-label={`${fallbackLabel} for: ${alt}`}
        >
          <img src={PLACEHOLDER_SVG} alt="" aria-hidden="true" className="safe-image-placeholder" />
          <span className="safe-image-fallback-text sr-only">{fallbackLabel}</span>
        </div>
      )}
    </div>
  );
}
