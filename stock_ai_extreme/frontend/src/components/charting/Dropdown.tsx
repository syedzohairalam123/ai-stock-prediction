/**
 * Phase 11 — a compact popover menu for the chart toolbar (spec §18, §24).
 *
 * The toolbar packs symbol, timeframe, style, indicators, drawings, levels and
 * settings into one row on a laptop, so the panels open as popovers anchored to
 * their trigger. Behaviour it guarantees for every menu:
 *   - closes on outside click and on Escape,
 *   - marks the trigger as expanded/active for assistive tech,
 *   - never lets a click inside the panel bubble out and close it by accident.
 */
import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";

export interface DropdownRenderApi {
  close: () => void;
}

interface DropdownProps {
  ariaLabel: string;
  title?: string;
  icon?: ReactNode;
  label?: string;
  /** Highlight the trigger when its mode is on / armed. */
  active?: boolean;
  align?: "left" | "right";
  panelClassName?: string;
  disabled?: boolean;
  hideChevron?: boolean;
  triggerClassName?: string;
  /** Either static content, or a render prop that receives the close handle. */
  children: ReactNode | ((api: DropdownRenderApi) => ReactNode);
}

export default function Dropdown({
  ariaLabel,
  title,
  icon,
  label,
  active = false,
  align = "left",
  panelClassName = "",
  disabled = false,
  hideChevron = false,
  triggerClassName = "",
  children,
}: DropdownProps) {
  const [open, setOpen] = useState(false);
  const wrapper = useRef<HTMLDivElement>(null);
  const panelId = useId();

  const close = useCallback(() => setOpen(false), []);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!wrapper.current) return;
      if (!wrapper.current.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="chart-dd" ref={wrapper}>
      <button
        type="button"
        className={`chart-btn${active ? " on" : ""} ${triggerClassName}`.trim()}
        onClick={() => setOpen((v) => !v)}
        aria-label={ariaLabel}
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        title={title ?? ariaLabel}
        disabled={disabled}
      >
        {icon}
        {label && <span className="chart-btn-label">{label}</span>}
        {!hideChevron && <ChevronDown size={12} className="chart-btn-caret" />}
      </button>
      {open && (
        <div
          id={panelId}
          className={`chart-pop ${align === "right" ? "right" : "left"} ${panelClassName}`.trim()}
          role="group"
          aria-label={ariaLabel}
        >
          {typeof children === "function" ? children({ close }) : children}
        </div>
      )}
    </div>
  );
}
