/**
 * Phase 8 — News timestamp formatting utilities
 * 
 * Formats timestamps for news articles with relative time display
 * (e.g., "2 minutes ago", "3 hours ago", "Yesterday")
 */

/**
 * Format a date to relative time string (e.g., "2 minutes ago")
 */
export function formatRelativeTime(dateString: string | null): string {
  if (!dateString) return "Date unknown";

  try {
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffSec = Math.floor(diffMs / 1000);
    const diffMin = Math.floor(diffSec / 60);
    const diffHour = Math.floor(diffMin / 60);
    const diffDay = Math.floor(diffHour / 24);

    // Future dates (should not happen, but handle gracefully)
    if (diffMs < 0) {
      return formatAbsoluteDate(dateString);
    }

    // Less than 1 minute
    if (diffSec < 60) {
      return "Just now";
    }

    // Less than 1 hour
    if (diffMin < 60) {
      return `${diffMin} ${diffMin === 1 ? "minute" : "minutes"} ago`;
    }

    // Less than 24 hours
    if (diffHour < 24) {
      return `${diffHour} ${diffHour === 1 ? "hour" : "hours"} ago`;
    }

    // Less than 7 days
    if (diffDay < 7) {
      if (diffDay === 1) return "Yesterday";
      return `${diffDay} days ago`;
    }

    // More than 7 days, show absolute date
    return formatAbsoluteDate(dateString);
  } catch (e) {
    return "Date unknown";
  }
}

/**
 * Format date to absolute format (e.g., "Jan 15, 2024")
 */
export function formatAbsoluteDate(dateString: string | null): string {
  if (!dateString) return "Date unknown";

  try {
    const date = new Date(dateString);
    return date.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  } catch (e) {
    return "Date unknown";
  }
}

/**
 * Format date with time (e.g., "Jan 15, 2024 at 3:45 PM")
 */
export function formatDateTime(dateString: string | null): string {
  if (!dateString) return "Date unknown";

  try {
    const date = new Date(dateString);
    return date.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
    });
  } catch (e) {
    return "Date unknown";
  }
}

/**
 * Format a timestamp as a plain clock time (e.g., "3:45 PM").
 * Used by the AI assistant thread, where the day is already obvious.
 */
export function formatClockTime(dateString: string | null): string {
  if (!dateString) return "";

  try {
    return new Date(dateString).toLocaleTimeString("en-US", {
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
    });
  } catch (e) {
    return "";
  }
}

/**
 * Group label for a conversation-history list (Today / Yesterday / date).
 */
export function formatDayGroup(dateString: string | null): string {
  if (!dateString) return "Earlier";

  try {
    const date = new Date(dateString);
    const now = new Date();
    const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    const time = date.getTime();

    if (time >= startOfToday) return "Today";
    if (time >= startOfToday - 86400000) return "Yesterday";
    if (time >= startOfToday - 7 * 86400000) return "Previous 7 days";
    return date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  } catch (e) {
    return "Earlier";
  }
}

/**
 * Format date for input fields (YYYY-MM-DD)
 */
export function formatDateForInput(dateString: string | Date | null): string {
  if (!dateString) return "";

  try {
    const date = typeof dateString === "string" ? new Date(dateString) : dateString;
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  } catch (e) {
    return "";
  }
}

/**
 * Get date range for filters (e.g., "Last 7 days")
 */
export function getDateRange(range: "today" | "week" | "month" | "year"): {
  from: string;
  to: string;
} {
  const now = new Date();
  const to = formatDateForInput(now);
  const from = new Date();

  switch (range) {
    case "today":
      from.setHours(0, 0, 0, 0);
      break;
    case "week":
      from.setDate(now.getDate() - 7);
      break;
    case "month":
      from.setMonth(now.getMonth() - 1);
      break;
    case "year":
      from.setFullYear(now.getFullYear() - 1);
      break;
  }

  return {
    from: formatDateForInput(from),
    to,
  };
}

/**
 * Check if date is today
 */
export function isToday(dateString: string | null): boolean {
  if (!dateString) return false;

  try {
    const date = new Date(dateString);
    const now = new Date();
    return (
      date.getDate() === now.getDate() &&
      date.getMonth() === now.getMonth() &&
      date.getFullYear() === now.getFullYear()
    );
  } catch (e) {
    return false;
  }
}

/**
 * Check if date is within last N days
 */
export function isWithinDays(dateString: string | null, days: number): boolean {
  if (!dateString) return false;

  try {
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
    return diffDays >= 0 && diffDays <= days;
  } catch (e) {
    return false;
  }
}
