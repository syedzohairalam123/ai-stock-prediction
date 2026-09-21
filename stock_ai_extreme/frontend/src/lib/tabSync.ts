/**
 * Phase 13 — cross-tab state sync.
 *
 * The terminal is routinely open in several tabs. Watchlist edits and the
 * search sidebar's recents should follow the user between them, without a
 * server round-trip.
 *
 * `BroadcastChannel` is the right primitive (structured messages, no storage
 * churn, fires only in *other* tabs). Where it is unavailable the helper falls
 * back to a `storage` event, which every browser that lacks BroadcastChannel
 * still delivers to sibling tabs.
 *
 * Messages carry an `origin` id so a receiver can ignore its own echo, and an
 * `at` timestamp so two tabs racing on the same write resolve deterministically.
 */
export interface TabEnvelope {
  at: number;
  origin: string;
}

/** A message is anything with a `type` discriminator; extra fields are free. */
export interface TabMessage {
  type: string;
}

export interface TabSyncHandle<Message extends TabMessage> {
  publish: (message: Message) => void;
  close: () => void;
}

const CHANNEL_PREFIX = "neural-market:";

/** Per-tab identity so a tab never applies its own broadcast. */
const ORIGIN = `tab-${Math.random().toString(36).slice(2, 10)}`;

/**
 * Create a sync handle for a named channel.
 *
 * `onMessage` runs for every *remote* message (never for the local echo) and is
 * wrapped so a throwing handler cannot break the event loop.
 */
export function createTabSync<Message extends TabMessage>(
  channelName: string,
  onMessage: (message: Message & TabEnvelope) => void
): TabSyncHandle<Message> {
  if (typeof window === "undefined") {
    return { publish: () => undefined, close: () => undefined };
  }

  const storageKey = `${CHANNEL_PREFIX}sync:${channelName}`;
  const handle = (message: (Message & Partial<TabEnvelope>) | null | undefined) => {
    if (!message || typeof message.type !== "string") return;
    if (message.origin === ORIGIN) return; // our own broadcast
    if (typeof message.at === "number" && typeof message.origin === "string") {
      // Fall through: a well-formed envelope from another tab.
    }
    try {
      onMessage({ ...message, at: message.at ?? Date.now(), origin: message.origin ?? "unknown" } as Message & TabEnvelope);
    } catch {
      // A bad message must never take down the tab.
    }
  };

  let channel: BroadcastChannel | null = null;
  if (typeof BroadcastChannel !== "undefined") {
    channel = new BroadcastChannel(`${CHANNEL_PREFIX}${channelName}`);
    channel.onmessage = (event: MessageEvent) => handle(event.data as Message & TabEnvelope);
  }

  const onStorage = (event: StorageEvent) => {
    if (event.key !== storageKey || !event.newValue) return;
    try {
      handle(JSON.parse(event.newValue) as Message & TabEnvelope);
    } catch {
      // Ignore unparseable payloads.
    }
  };
  window.addEventListener("storage", onStorage);

  return {
    publish(message) {
      const envelope = { ...message, at: Date.now(), origin: ORIGIN } as Message & TabEnvelope;
      if (channel) {
        channel.postMessage(envelope);
        return;
      }
      try {
        window.localStorage.setItem(storageKey, JSON.stringify(envelope));
      } catch {
        // Quota/privacy mode — sync is best-effort.
      }
    },
    close() {
      channel?.close();
      window.removeEventListener("storage", onStorage);
    },
  };
}
