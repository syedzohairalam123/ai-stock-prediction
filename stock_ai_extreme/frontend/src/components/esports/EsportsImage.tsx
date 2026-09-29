/**
 * Phase 21B §19 — image handling.
 *
 * Team logos and player avatars come from the provider (or are absent). These
 * components always: lazy-load, carry real alt text, degrade to a labelled
 * fallback on error or when there is no URL at all, and never substitute a
 * generated identity for a real team/player (§19).
 */
import { useEffect, useState } from "react";

export function TeamLogo({
  src,
  name,
  size = 44,
  className = "",
}: {
  src: string | null | undefined;
  name: string | null | undefined;
  size?: number;
  className?: string;
}) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [src]);
  const label = name || "Team";
  const initials = label
    .split(/\s+/)
    .map((part) => part[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase();

  const showImage = Boolean(src) && !failed;
  return (
    <span
      className={`esp-logo ${className}`.trim()}
      style={{ width: size, height: size }}
      data-image-state={showImage ? "loaded" : "fallback"}
    >
      {showImage ? (
        <img
          src={src as string}
          alt={`${label} logo`}
          loading="lazy"
          decoding="async"
          referrerPolicy="no-referrer"
          onError={() => setFailed(true)}
        />
      ) : (
        <span className="esp-logo-fallback" role="img" aria-label={`${label} — no logo available`}>
          {initials || "?"}
        </span>
      )}
    </span>
  );
}

export function PlayerAvatar({
  src,
  name,
  size = 40,
  className = "",
}: {
  src: string | null | undefined;
  name: string | null | undefined;
  size?: number;
  className?: string;
}) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [src]);
  const label = name || "Player";
  const showImage = Boolean(src) && !failed;
  return (
    <span
      className={`esp-avatar ${className}`.trim()}
      style={{ width: size, height: size }}
      data-image-state={showImage ? "loaded" : "fallback"}
    >
      {showImage ? (
        <img
          src={src as string}
          alt={`${label} avatar`}
          loading="lazy"
          decoding="async"
          referrerPolicy="no-referrer"
          onError={() => setFailed(true)}
        />
      ) : (
        <span className="esp-avatar-fallback" role="img" aria-label={`${label} — no avatar available`}>
          {label.slice(0, 1).toUpperCase()}
        </span>
      )}
    </span>
  );
}
