/**
 * Phase 12 — WidgetFrame (spec §11, §16, §19).
 *
 * The chrome every widget shares: a header (drag handle + title + controls)
 * and a body. Controls never interfere with widget internals — the drag handle
 * is the header only, so charts keep their own gestures inside the body.
 *
 * Isolation (§16): each frame owns its boundary. A widget that throws shows a
 * scoped error card with Retry; every other widget keeps running. Hidden
 * widgets render nothing (§18) and minimized widgets unmount their body while
 * keeping their settings alive in the store.
 */
import { Component, ErrorInfo, memo, ReactNode, useCallback } from "react";
import {
  ChevronsDownUp,
  ChevronsUpDown,
  Eye,
  EyeOff,
  Maximize2,
  Minimize2,
  Minus,
  Settings2,
  X,
} from "lucide-react";
import { boundsFor, descriptorFor } from "../../lib/workspace/registry";
import { useWorkspaceStore } from "../../store/useWorkspaceStore";
import type { WidgetInstance } from "../../lib/workspace/types";

interface WidgetFrameProps {
  widget: WidgetInstance;
  /** Grid unit → pixel maths stay in the grid; frames only get children. */
  children: (bodyVisible: boolean) => ReactNode;
}

// ---------------------------------------------------------------------------
// Per-widget error boundary (spec §16)
// ---------------------------------------------------------------------------

class WidgetErrorBoundary extends Component<
  { name: string; onRetryKey: string; children: ReactNode },
  { error: Error | null }
> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Scoped, honest logging: the dashboard must survive one broken widget.
    console.error(`[workspace] widget "${this.props.name}" failed:`, error, info.componentStack);
  }

  componentDidUpdate(prev: { onRetryKey: string }) {
    // A retry (remount) clears the error state via a key change upstream; when
    // the boundary itself survives, reset so the widget can render again.
    if (prev.onRetryKey !== this.props.onRetryKey && this.state.error) {
      this.setState({ error: null });
    }
  }

  render() {
    if (this.state.error) {
      return (
        <div className="ws-widget-error" role="alert">
          <b>{this.props.name} failed</b>
          <span>{this.state.error.message || "Unexpected error."}</span>
          <p className="ws-widget-error-note">
            Other widgets are unaffected. Retry re-mounts only this widget.
          </p>
        </div>
      );
    }
    return this.props.children;
  }
}

// ---------------------------------------------------------------------------
// Settings popover
// ---------------------------------------------------------------------------

function WidgetSettingsPanel({ widget }: { widget: WidgetInstance }) {
  const patchWidgetSettings = useWorkspaceStore((s) => s.patchWidgetSettings);
  const removeWidgetById = useWorkspaceStore((s) => s.removeWidgetById);

  if (widget.type === "NEW_CHART") {
    return (
      <div className="ws-widget-settings" role="group" aria-label={`${descriptorFor(widget.type).name} settings`}>
        <label>
          Symbol
          <input
            defaultValue={typeof widget.settings.symbol === "string" ? widget.settings.symbol : "OGDC"}
            onBlur={(e) => patchWidgetSettings(widget.id, { symbol: e.target.value.trim().toUpperCase() })}
            aria-label="Chart symbol"
            size={8}
          />
        </label>
        <small>Full chart controls live inside the chart itself.</small>
      </div>
    );
  }
  if (widget.type === "CATALYSTS_NEWS") {
    return (
      <div className="ws-widget-settings" role="group" aria-label="News settings">
        <label>
          Ticker
          <input
            defaultValue={typeof widget.settings.ticker === "string" ? widget.settings.ticker : ""}
            placeholder="Empty = whole market"
            onBlur={(e) => patchWidgetSettings(widget.id, { ticker: e.target.value.trim().toUpperCase() })}
            aria-label="News ticker"
            size={10}
          />
        </label>
        <small>The scope selector inside the widget does the same thing.</small>
      </div>
    );
  }
  return (
    <div className="ws-widget-settings" role="group" aria-label={`${descriptorFor(widget.type).name} settings`}>
      <small>{descriptorFor(widget.type).description}</small>
      <button type="button" className="ws-btn ghost sm" onClick={() => removeWidgetById(widget.id)}>
        Remove widget
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Frame
// ---------------------------------------------------------------------------

function WidgetFrameInner({ widget, children }: WidgetFrameProps) {
  const hideWidget = useWorkspaceStore((s) => s.hideWidget);
  const showWidget = useWorkspaceStore((s) => s.showWidget);
  const minimizeWidget = useWorkspaceStore((s) => s.minimizeWidget);
  const maximizeWidget = useWorkspaceStore((s) => s.maximizeWidget);
  const removeWidgetById = useWorkspaceStore((s) => s.removeWidgetById);

  const descriptor = descriptorFor(widget.type);
  const Icon = descriptor.icon as React.ComponentType<{ size?: number; "aria-hidden"?: boolean }>;
  const bounds = boundsFor(widget.type);

  const anyMaximized = useWorkspaceStore((s) => s.layouts[s.preset].widgets.some((w) => w.maximized));

  const onHide = useCallback(() => hideWidget(widget.id), [hideWidget, widget.id]);
  const onShow = useCallback(() => showWidget(widget.id), [showWidget, widget.id]);
  const onMinimize = useCallback(() => minimizeWidget(widget.id, !widget.minimized), [minimizeWidget, widget.id, widget.minimized]);
  const onMaximize = useCallback(() => maximizeWidget(widget.id, !widget.maximized), [maximizeWidget, widget.id, widget.maximized]);
  const onClose = useCallback(() => removeWidgetById(widget.id), [removeWidgetById, widget.id]);

  // Hidden widgets render nothing — but the hidden state is reversible from
  // the workspace's Hidden widgets menu, so the data is never lost.
  if (!widget.visible) return null;

  const bodyVisible = !widget.minimized && !widget.maximized ? true : widget.maximized ? true : false;
  const showBody = !widget.minimized;

  return (
    <section
      className={`ws-widget${widget.minimized ? " minimized" : ""}${widget.maximized ? " maximized" : ""}`}
      aria-label={`${descriptor.name} widget`}
    >
      <header className="ws-widget-head" title={`Drag to move · ${descriptor.description}`}>
        <button
          type="button"
          className="ws-widget-drag"
          aria-hidden="true"
          tabIndex={-1}
          onClick={(e) => e.preventDefault()}
        >
          <Icon size={13} aria-hidden />
          <span className="ws-widget-title">{descriptor.name}</span>
          <span className="ws-widget-sub" aria-hidden>
            {widget.minimized ? "minimized" : ""}
          </span>
        </button>

        <div className="ws-widget-controls" role="group" aria-label={`${descriptor.name} controls`}>
          {widget.visible && (
            <button type="button" className="ws-ctl" onClick={onHide} aria-label={`Hide ${descriptor.name}`} title="Hide (keeps its data)">
              <EyeOff size={13} aria-hidden />
            </button>
          )}
          <button
            type="button"
            className="ws-ctl"
            onClick={onMinimize}
            aria-label={widget.minimized ? `Restore ${descriptor.name}` : `Minimize ${descriptor.name}`}
            aria-pressed={widget.minimized}
            title={widget.minimized ? "Restore" : "Minimize"}
          >
            {widget.minimized ? <ChevronsUpDown size={13} aria-hidden /> : <Minus size={13} aria-hidden />}
          </button>
          <button
            type="button"
            className="ws-ctl"
            onClick={onMaximize}
            aria-label={widget.maximized ? `Restore ${descriptor.name}` : `Maximize ${descriptor.name}`}
            aria-pressed={widget.maximized}
            disabled={widget.minimized}
            title={widget.maximized ? "Restore layout" : "Maximize"}
          >
            {widget.maximized ? <Minimize2 size={13} aria-hidden /> : <Maximize2 size={13} aria-hidden />}
          </button>
          <span className="ws-widget-menu" data-widget-menu>
            <WidgetMenu widget={widget} />
          </span>
          {bounds.minSize.w > 0 && (
            <button type="button" className="ws-ctl" onClick={onClose} aria-label={`Close ${descriptor.name}`} title="Close (removes from layout)">
              <X size={13} aria-hidden />
            </button>
          )}
        </div>
      </header>

      {showBody ? (
        <WidgetErrorBoundary name={descriptor.name} onRetryKey={`${widget.id}:${widget.settings ? Object.keys(widget.settings).length : 0}`}>
          {children(bodyVisible && !widget.minimized)}
        </WidgetErrorBoundary>
      ) : (
        <div className="ws-widget-body-collapsed" aria-hidden />
      )}
    </section>
  );
}

/** Settings + show/hide + remove popover, closed by default. */
function WidgetMenu({ widget }: { widget: WidgetInstance }) {
  const hideWidget = useWorkspaceStore((s) => s.hideWidget);
  const showWidget = useWorkspaceStore((s) => s.showWidget);
  const removeWidgetById = useWorkspaceStore((s) => s.removeWidgetById);
  const descriptor = descriptorFor(widget.type);

  const openClass = "ws-widget-pop";
  return (
    <details className={openClass}>
      <summary className="ws-ctl" aria-label={`${descriptor.name} settings`} title="Settings">
        <Settings2 size={13} aria-hidden />
      </summary>
      <div className="ws-widget-pop-body" onClick={(e) => e.stopPropagation()}>
        <WidgetSettingsPanel widget={widget} />
        <div className="ws-widget-pop-actions">
          {widget.visible ? (
            <button type="button" className="ws-btn ghost sm" onClick={() => hideWidget(widget.id)}>
              <Eye size={12} aria-hidden /> Hide
            </button>
          ) : null}
          <button type="button" className="ws-btn ghost sm danger" onClick={() => removeWidgetById(widget.id)}>
            Remove
          </button>
        </div>
      </div>
      {/* Unused show path stays available for programmatic restore */}
      <span className="sr-only">
        <button type="button" onClick={() => showWidget(widget.id)}>
          Show
        </button>
      </span>
    </details>
  );
}

const WidgetFrame = memo(WidgetFrameInner);
export default WidgetFrame;
