/**
 * Phase 11 — the chart toolbar (spec §24).
 *
 * Everything one panel needs, in two compact rows:
 *
 *   row 1  panel label · symbol · timeframe · chart style · data provenance
 *   row 2  drawing tools · price levels · indicators · volume/crosshair ·
 *          settings · fit · fullscreen
 *
 * The toolbar only ever calls store actions; the plot and the annotation layer
 * react to the store, so there is a single source of truth for panel state.
 */
import {
  AreaChart,
  BarChart3,
  Crosshair,
  Gauge,
  Grid2x2,
  LineChart,
  Link2,
  Link2Off,
  Maximize2,
  Minimize2,
  RotateCcw,
  Ruler,
  Settings2,
} from "lucide-react";
import type { ReactNode } from "react";
import type { IndicatorConfig, IndicatorType, PriceLevel, PriceLevelType } from "../../lib/charting/types";
import type { ChartInstance, ChartStyle, DrawingShape, DrawingStyle, DrawingTool, EntityType } from "../../lib/charting/types";
import type { StockRange } from "../../lib/timeframes";
import type { IndicatorUnavailable } from "../../lib/charting/indicators";
import { CHART_STYLES, TIMEFRAME_OPTIONS } from "../../lib/charting/defaults";
import Dropdown from "./Dropdown";
import DrawingToolbar from "./DrawingToolbar";
import IndicatorMenu from "./IndicatorMenu";
import PriceLevelMenu from "./PriceLevelMenu";
import SymbolSearch from "./SymbolSearch";

export type PanelDataState = "loading" | "error" | "ready";

const STYLE_ICON: Record<ChartStyle, ReactNode> = {
  candles: <Gauge size={14} />,
  "volume-candles": <BarChart3 size={14} />,
  line: <LineChart size={14} />,
};

interface ChartToolbarProps {
  instance: ChartInstance;
  label: string;
  isActive: boolean;
  isSplit: boolean;
  entityName: string;
  dataState: PanelDataState;
  unavailable: IndicatorUnavailable[];
  controller: {
    tool: DrawingTool;
    priceLevelTool: PriceLevelType | null;
    onTool: (tool: DrawingTool) => void;
  };
  selectedDrawing: DrawingShape | null;
  selectedLevel: PriceLevel | null;
  canUndo: boolean;
  canRedo: boolean;
  isFullscreen: boolean;
  lastClose: number | null;

  /** Phase 11 — cross-panel linking (global switch + this panel's membership). */
  linkEnabled: boolean;
  linkGroup: { symbol: boolean; timeframe: boolean; crosshair: boolean };
  panelLinked: boolean;
  /** Every open panel, so the toolbar can drive the whole group from one menu. */
  linkPanels: { id: string; label: string; linked: boolean }[];

  onToggleLinkEnabled: () => void;
  onLinkGroup: (patch: Partial<{ symbol: boolean; timeframe: boolean; crosshair: boolean }>) => void;
  onTogglePanelLink: (id: string) => void;

  onActivate: () => void;
  onSymbol: (symbol: string, entityType: EntityType) => void;
  onEntityType: (entityType: EntityType) => void;
  onTimeframe: (timeframe: StockRange) => void;
  onChartStyle: (style: ChartStyle) => void;
  onToggleVolume: () => void;
  onToggleCrosshair: () => void;
  onSettings: (patch: Partial<ChartInstance["settings"]>) => void;
  onToggleIndicator: (indicatorId: string) => void;
  onUpdateIndicator: (indicatorId: string, patch: Partial<IndicatorConfig>) => void;
  onAddIndicator: (type: IndicatorType, period: number) => void;
  onRemoveIndicator: (indicatorId: string) => void;
  onResetIndicators: () => void;
  onUndo: () => void;
  onRedo: () => void;
  onDeleteSelected: () => void;
  onClearDrawings: () => void;
  onStyleDrawing: (patch: Partial<DrawingStyle>) => void;
  onToggleDrawingVisible: () => void;
  onToggleDrawingLocked: () => void;
  onArmPriceLevel: (type: PriceLevelType | null) => void;
  onPlacePriceLevel: (type: PriceLevelType, price: number) => void;
  onUpdatePriceLevel: (levelId: string, patch: Partial<PriceLevel>) => void;
  onDeletePriceLevel: (levelId: string) => void;
  onClearPriceLevels: () => void;
  onSelect: (id: string | null) => void;
  onResetView: () => void;
  onResetChart: () => void;
  onToggleFullscreen: () => void;
}

export default function ChartToolbar(props: ChartToolbarProps) {
  const {
    instance,
    label,
    isActive,
    isSplit,
    entityName,
    dataState,
    unavailable,
    controller,
    selectedDrawing,
    selectedLevel,
    canUndo,
    canRedo,
    isFullscreen,
    lastClose,
    linkEnabled,
    linkGroup,
    panelLinked,
    linkPanels,
  } = props;

  const volumeLocked = instance.chartType === "volume-candles";
  const enabledIndicators = instance.indicators.filter((i) => i.enabled).length;
  const armed = controller.priceLevelTool !== null;

  return (
    <div className="chart-toolbar">
      <div className="chart-toolbar-row">
        <button
          type="button"
          className={`chart-panel-tag${isActive ? " on" : ""}`}
          onClick={props.onActivate}
          title={isSplit ? `Make ${label} the active chart` : `${label} is the only chart`}
          aria-pressed={isActive}
        >
          {label}
        </button>

        <SymbolSearch
          value={instance.symbol}
          entityType={instance.entityType}
          entityName={entityName}
          onCommit={props.onSymbol}
          onEntityType={props.onEntityType}
          disabled={dataState === "loading"}
        />

        <div className="chart-tf" role="group" aria-label="Timeframe">
          {TIMEFRAME_OPTIONS.map((timeframe) => (
            <button
              key={timeframe}
              type="button"
              className={timeframe === instance.timeframe ? "on" : ""}
              onClick={() => props.onTimeframe(timeframe)}
              aria-pressed={timeframe === instance.timeframe}
              title={`${timeframe} bars`}
            >
              {timeframe}
            </button>
          ))}
        </div>

        <Dropdown ariaLabel="Chart style" icon={STYLE_ICON[instance.chartType]} label={styleLabel(instance.chartType)}>
          {({ close }) => (
            <div className="chart-pop-body">
              <div className="chart-pop-head">
                <span>Chart style</span>
              </div>
              {CHART_STYLES.map((style) => (
                <button
                  key={style.id}
                  type="button"
                  className={`chart-pop-item${style.id === instance.chartType ? " on" : ""}`}
                  onClick={() => {
                    props.onChartStyle(style.id);
                    close();
                  }}
                  title={style.hint}
                >
                  <span className="chart-pop-item-icon">{STYLE_ICON[style.id]}</span>
                  <span className="chart-pop-item-label">
                    {style.label}
                    <em>{style.hint}</em>
                  </span>
                </button>
              ))}
            </div>
          )}
        </Dropdown>
      </div>

      <div className="chart-toolbar-row">
        <DrawingToolbar
          tool={controller.tool}
          drawingCount={instance.drawings.length}
          selected={selectedDrawing}
          canUndo={canUndo}
          canRedo={canRedo}
          onTool={controller.onTool}
          onUndo={props.onUndo}
          onRedo={props.onRedo}
          onDelete={props.onDeleteSelected}
          onClear={props.onClearDrawings}
          onStyle={props.onStyleDrawing}
          onToggleVisible={props.onToggleDrawingVisible}
          onToggleLock={props.onToggleDrawingLocked}
          disabled={dataState !== "ready"}
        />

        <span className="chart-toolgroup-sep" aria-hidden="true" />

        <Dropdown
          ariaLabel="Price level tools"
          icon={<Ruler size={15} />}
          label="Levels"
          active={armed || instance.priceLevels.length > 0}
          triggerClassName={armed ? "armed" : ""}
        >
          <PriceLevelMenu
            instance={instance}
            armedType={controller.priceLevelTool}
            selectedId={props.selectedLevel?.id ?? null}
            lastClose={lastClose}
            onArm={props.onArmPriceLevel}
            onPlace={props.onPlacePriceLevel}
            onSelect={props.onSelect}
            onUpdate={props.onUpdatePriceLevel}
            onDelete={props.onDeletePriceLevel}
            onClear={props.onClearPriceLevels}
          />
        </Dropdown>

        <Dropdown
          ariaLabel="Indicators"
          icon={<AreaChart size={15} />}
          label={`Indicators${enabledIndicators ? ` ${enabledIndicators}` : ""}`}
          active={enabledIndicators > 0}
          align="right"
          panelClassName="chart-pop-wide"
        >
          <IndicatorMenu
            instance={instance}
            unavailable={unavailable}
            onToggle={props.onToggleIndicator}
            onUpdate={props.onUpdateIndicator}
            onAdd={props.onAddIndicator}
            onRemove={props.onRemoveIndicator}
            onReset={props.onResetIndicators}
          />
        </Dropdown>

        <Dropdown
          ariaLabel="Cross-panel linking"
          icon={linkEnabled ? <Link2 size={15} /> : <Link2Off size={15} />}
          label="Link"
          active={linkEnabled}
          align="right"
          panelClassName="chart-pop-wide"
        >
          <div className="chart-pop-body">
            <div className="chart-pop-head">
              <span>Cross-panel linking</span>
            </div>

            <label className="chart-pop-check">
              <input type="checkbox" checked={linkEnabled} onChange={props.onToggleLinkEnabled} />
              <Link2 size={14} /> Sync panels
            </label>
            <p className="chart-pop-note">
              {linkEnabled
                ? "Linked properties follow you across the panels that joined the group."
                : "Off — every panel keeps its own symbol, timeframe and crosshair."}
            </p>

            <div className={`chart-pop-sub${linkEnabled ? "" : " dim"}`}>
              <span className="chart-pop-subhead">Linked properties</span>
              <label className="chart-pop-check">
                <input
                  type="checkbox"
                  checked={linkGroup.symbol}
                  disabled={!linkEnabled}
                  onChange={(event) => props.onLinkGroup({ symbol: event.target.checked })}
                />
                Symbol
              </label>
              <label className="chart-pop-check">
                <input
                  type="checkbox"
                  checked={linkGroup.timeframe}
                  disabled={!linkEnabled}
                  onChange={(event) => props.onLinkGroup({ timeframe: event.target.checked })}
                />
                Timeframe
              </label>
              <label className="chart-pop-check">
                <input
                  type="checkbox"
                  checked={linkGroup.crosshair}
                  disabled={!linkEnabled}
                  onChange={(event) => props.onLinkGroup({ crosshair: event.target.checked })}
                />
                Crosshair
              </label>
            </div>

            <div className={`chart-pop-sub${linkEnabled ? "" : " dim"}`}>
              <span className="chart-pop-subhead">Panels in the group</span>
              {linkPanels.map((panel) => (
                <label key={panel.id} className="chart-pop-check">
                  <input
                    type="checkbox"
                    checked={panel.linked}
                    disabled={!linkEnabled}
                    onChange={() => props.onTogglePanelLink(panel.id)}
                  />
                  {panel.label}
                  {panel.id === instance.id && <em> (this panel)</em>}
                </label>
              ))}
            </div>
          </div>
        </Dropdown>

        <button
          type="button"
          className={`chart-icon-btn${linkEnabled && panelLinked ? " on" : ""}`}
          onClick={() => props.onTogglePanelLink(instance.id)}
          disabled={!linkEnabled}
          aria-pressed={linkEnabled && panelLinked}
          aria-label="Toggle this panel's link-group membership"
          title={
            linkEnabled
              ? panelLinked
                ? "This panel follows the link group — click to make it independent"
                : "This panel is independent — click to add it to the link group"
              : "Turn on cross-panel linking (Link menu) to use this"
          }
        >
          {linkEnabled && panelLinked ? <Link2 size={15} /> : <Link2Off size={15} />}
        </button>

        <button
          type="button"
          className={`chart-icon-btn${instance.volumeVisible && !volumeLocked ? " on" : ""}`}
          onClick={props.onToggleVolume}
          aria-pressed={instance.volumeVisible}
          disabled={volumeLocked}
          aria-label="Toggle volume pane"
          title={volumeLocked ? "The volume-candles style always shows volume" : "Show/hide the volume pane"}
        >
          <BarChart3 size={15} />
        </button>

        <button
          type="button"
          className={`chart-icon-btn${instance.crosshairEnabled ? " on" : ""}`}
          onClick={props.onToggleCrosshair}
          aria-pressed={instance.crosshairEnabled}
          aria-label="Toggle crosshair"
          title="Crosshair and OHLCV readout"
        >
          <Crosshair size={15} />
        </button>

        <Dropdown ariaLabel="Chart settings" icon={<Settings2 size={15} />} hideChevron align="right">
          <div className="chart-pop-body">
            <div className="chart-pop-head">
              <span>Display</span>
            </div>
            <label className="chart-pop-check">
              <input
                type="checkbox"
                checked={instance.settings.grid}
                onChange={(event) => props.onSettings({ grid: event.target.checked })}
              />
              <Grid2x2 size={14} /> Grid lines
            </label>
            <label className="chart-pop-check">
              <input
                type="checkbox"
                checked={instance.settings.legend}
                onChange={(event) => props.onSettings({ legend: event.target.checked })}
              />
              <AreaChart size={14} /> Indicator legend
            </label>
            <label className="chart-pop-check">
              <input
                type="checkbox"
                checked={instance.settings.lastPriceLine}
                onChange={(event) => props.onSettings({ lastPriceLine: event.target.checked })}
              />
              <Crosshair size={14} /> Last price line
            </label>
            <div className="chart-pop-footer">
              <button type="button" className="chart-btn ghost" onClick={props.onResetView}>
                <RotateCcw size={13} />
                <span className="chart-btn-label">Reset view (fit data)</span>
              </button>
              <button type="button" className="chart-btn ghost danger" onClick={props.onResetChart}>
                <RotateCcw size={13} />
                <span className="chart-btn-label">Reset this chart</span>
              </button>
            </div>
          </div>
        </Dropdown>

        <button
          type="button"
          className="chart-icon-btn"
          onClick={props.onToggleFullscreen}
          aria-pressed={isFullscreen}
          aria-label={isFullscreen ? "Exit fullscreen" : "Enter fullscreen"}
          title={isFullscreen ? "Exit fullscreen (Esc)" : "Fullscreen this chart"}
        >
          {isFullscreen ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
        </button>

        {armed && (
          <span className="chart-armed-hint" role="status">
            Click the chart to place a {controller.priceLevelTool?.toLowerCase().replace("_", " ")} level
          </span>
        )}
      </div>
    </div>
  );
}

function styleLabel(style: ChartStyle): string {
  return CHART_STYLES.find((s) => s.id === style)?.label ?? "Candlestick";
}
