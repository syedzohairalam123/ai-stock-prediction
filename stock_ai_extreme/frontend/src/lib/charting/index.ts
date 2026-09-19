/**
 * Phase 11 — Professional charting & technical-analysis engine.
 *
 * Public surface of the engine, grouped by responsibility:
 *
 *   types.ts       data models (chart instance, drawings, price levels, candles)
 *   math.ts        reusable statistical primitives
 *   indicators.ts  SMA / EMA / VWAP / Bollinger Bands + memoized compute
 *   ohlcv.ts       normalization & provider adapters
 *   geometry.ts    data-space ⇄ pixel mapping for annotations
 *   drawings.ts    drawing & price-level model helpers
 *   defaults.ts    catalogs and the chart-instance factory
 *   dataSource.ts  unified stock/index dataset loader
 *
 * React components live in `components/charting/`, the persisted workspace state
 * in `store/useChartStore.ts` and the data hook in `hooks/useChartData.ts`.
 */
export * from "./types";
export * from "./math";
export * from "./indicators";
export * from "./ohlcv";
export * from "./geometry";
export * from "./drawings";
export * from "./defaults";
export * from "./dataSource";
