/**
 * Phase 22C — Crypto Volatility Markets terminal.
 *
 * The complete user-facing surface over the Phase 22A/22B engines:
 *   • subcategories ALL / PRE-MARKET / INSTITUTIONS / TARGETS / INDUSTRY, each
 *     backed by a real endpoint (§1/§2);
 *   • the premium market header, a prominent timeframe selector (§3/§4);
 *   • micro-trend + volatility cards and a trend timeline (§5–§7);
 *   • the MODELLED FORECAST card with provenance and validation (§8/§9/§35);
 *   • the target ladder, comparison and threshold analyzer (§10–§13);
 *   • one shared WebSocket for live ticks/current candles, with connection
 *     state, freshness and source badges (§19–§22);
 *   • per-widget error isolation, skeletons and empty states (§23–§25).
 *
 * Everything is additive: the Phase 22A page it grew from and the legacy
 * `/crypto` overview both remain untouched in behaviour.
 */
import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { CryptoAssetSelector } from "../components/crypto/CryptoAssetSelector";
import { CryptoLiveTicker } from "../components/crypto/CryptoLiveTicker";
import { CryptoCandleChart } from "../components/crypto/CryptoCandleChart";
import { CryptoDataQualityPanel } from "../components/crypto/CryptoDataQualityPanel";
import { CryptoAnalyticsPanel } from "../components/crypto/CryptoAnalyticsPanel";
import { CryptoMultiTimeframePanel } from "../components/crypto/CryptoMultiTimeframePanel";
import { CryptoSourcesPanel } from "../components/crypto/CryptoSourcesPanel";
import { CryptoSubcategoryNav, subcategoryHint, type CryptoSubcategory } from "../components/crypto/CryptoSubcategoryNav";
import { CryptoMicroTrendCard, CryptoVolatilityCard, CryptoMicroTrendChart } from "../components/crypto/CryptoSignalPanels";
import { CryptoForecastPanel } from "../components/crypto/CryptoForecastPanel";
import { CryptoTargetsPanel } from "../components/crypto/CryptoTargetsPanel";
import {
  CryptoIndustryView,
  CryptoInstitutionsView,
  CryptoPreMarketView,
} from "../components/crypto/CryptoCategoryPanels";
import { useCryptoSocket } from "../hooks/useCryptoSocket";
import {
  useCryptoAnalytics,
  useCryptoAssets,
  useCryptoCandles,
  useCryptoForecast,
  useCryptoHealth,
  useCryptoIndustry,
  useCryptoInstitutions,
  useCryptoMultiTimeframe,
  useCryptoPreSession,
  useCryptoQuote,
  useCryptoSources,
  useCryptoTargets,
  useCryptoTimeframes,
} from "../hooks/useCryptoQueries";
import { useCryptoStore } from "../store/useCryptoStore";
import { useAIStore } from "../store/useAIStore";
import { formatDateTime, NA, statusTone } from "../lib/cryptoFormat";

const DEFAULT_SYMBOL = "BTC";

function readParam(key: string): string | null {
  try {
    return new URLSearchParams(window.location.search).get(key);
  } catch {
    return null;
  }
}

export default function CryptoMarketTerminalPage() {
  const queryClient = useQueryClient();

  const [symbol, setSymbol] = useState(() => (readParam("symbol") || DEFAULT_SYMBOL).toUpperCase());
  const [timeframe, setTimeframe] = useState<string | null>(() => readParam("timeframe"));
  const [subcategory, setSubcategory] = useState<CryptoSubcategory>("ALL");
  const [horizon, setHorizon] = useState(5);

  const assetsQ = useCryptoAssets();
  const timeframesQ = useCryptoTimeframes();
  const sourcesQ = useCryptoSources();
  const healthQ = useCryptoHealth();

  useEffect(() => {
    if (timeframe === null && timeframesQ.data?.default) setTimeframe(timeframesQ.data.default);
  }, [timeframe, timeframesQ.data?.default]);

  const activeTimeframe = timeframe ?? timeframesQ.data?.default ?? "5m";
  const timeframeConfig = timeframesQ.data?.timeframes.find((t) => t.id === activeTimeframe);
  const capability = timeframesQ.data?.capabilities.find((c) => c.id === activeTimeframe);
  const limit = Math.min(timeframeConfig?.max_history_candles ?? 600, 600);

  const quoteQ = useCryptoQuote(symbol);
  const candlesQ = useCryptoCandles(symbol, activeTimeframe, limit, { displayPoints: 600 });
  const analyticsQ = useCryptoAnalytics(symbol, activeTimeframe);
  const multiQ = useCryptoMultiTimeframe(symbol);
  const forecastQ = useCryptoForecast(symbol, activeTimeframe, horizon, subcategory === "ALL");
  const targetsQ = useCryptoTargets(symbol);
  const preSessionQ = useCryptoPreSession();
  const institutionsQ = useCryptoInstitutions(symbol);
  const industryQ = useCryptoIndustry();

  // ---- live stream (one shared gateway socket, spec §14/§19) --------------
  useCryptoSocket({ symbol, timeframe: activeTimeframe });
  const connection = useCryptoStore((s) => s.connection);
  const lastMessageAt = useCryptoStore((s) => s.lastMessageAt);
  const liveTick = useCryptoStore((s) => s.ticks[symbol.toUpperCase()]);
  const channelKey = `${symbol.toUpperCase()}:${activeTimeframe}`;
  const liveTail = useCryptoStore((s) => s.candleTails[channelKey]);

  const selectedAsset = useMemo(
    () => assetsQ.data?.assets.find((a) => a.symbol === symbol),
    [assetsQ.data, symbol]
  );

  // Deep-linkable state: keep the URL in sync without a navigation.
  useEffect(() => {
    try {
      const params = new URLSearchParams(window.location.search);
      params.set("symbol", symbol);
      if (activeTimeframe) params.set("timeframe", activeTimeframe);
      window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}`);
    } catch {
      /* history is unavailable in some embeddings — non-fatal */
    }
  }, [symbol, activeTimeframe]);

  // Phase 22C §29: publish a normalized context to the AI assistant store.
  useEffect(() => {
    const snapshot = {
      asset_class: "crypto",
      symbol,
      timeframe: activeTimeframe,
      currentPrice: liveTick?.price ?? quoteQ.data?.price ?? null,
      change24hPercent: quoteQ.data?.change_percent_24h ?? null,
      trend: analyticsQ.data?.trend?.direction ?? null,
      trendStrength: analyticsQ.data?.trend?.strength ?? null,
      volatilityRegime: analyticsQ.data?.volatility?.regime ?? null,
      realizedVolatility: analyticsQ.data?.volatility?.realized_volatility ?? null,
      forecast: forecastQ.data?.forecast
        ? {
            prediction: forecastQ.data.forecast.prediction,
            lower: forecastQ.data.forecast.lower_bound,
            upper: forecastQ.data.forecast.upper_bound,
            model: forecastQ.data.forecast.model_name,
            horizon,
            origin: forecastQ.data.forecast.origin,
          }
        : null,
      targets: (targetsQ.data?.targets ?? []).map((row) => ({
        price: row.target.target_price,
        status: row.status,
        distancePercent: row.proximity?.distance_percent ?? null,
      })),
      dataQuality: analyticsQ.data?.quality?.label ?? candlesQ.data?.quality?.label ?? null,
      valueOrigins: {
        price: "SOURCE",
        trend: "DERIVED",
        volatility: "CALCULATED",
        forecast: "MODELLED",
        targets: "CALCULATED",
      },
    };
    useAIStore.getState().setContextSnapshot(snapshot);
  }, [
    symbol,
    activeTimeframe,
    horizon,
    liveTick?.price,
    quoteQ.data,
    analyticsQ.data,
    forecastQ.data,
    targetsQ.data,
    candlesQ.data,
  ]);

  function refreshAll() {
    queryClient.invalidateQueries({ queryKey: ["crypto"] });
  }

  const connectionLabel =
    connection === "connected"
      ? "CONNECTED"
      : connection === "reconnecting"
        ? "RECONNECTING"
        : connection === "connecting"
          ? "CONNECTING"
          : "DISCONNECTED";

  return (
    <main className="crypto-terminal">
      <header className="crypto-terminal-head">
        <div>
          <p className="crypto-eyebrow">Phase 22C · real market data · modelled analytics</p>
          <h1>Crypto Volatility Markets</h1>
          <p className="crypto-lede">
            Live OHLCV from Binance spot REST/WebSocket plus CoinGecko public API. Volatility,
            micro-trend, forecasts and targets are computed on this real history — never on sample or
            placeholder data.
          </p>
        </div>
        <div className="crypto-terminal-actions">
          <span className={`crypto-conn ${connection}`} title={`Live gateway: ${connection}`}>
            <span className="crypto-conn-dot" aria-hidden />
            {connectionLabel}
          </span>
          <button type="button" className="crypto-probe-btn" onClick={refreshAll}>
            Refresh
          </button>
        </div>
      </header>

      {connection === "disconnected" && (
        <div className="crypto-warn" role="alert">
          <strong>LIVE DATA CONNECTION LOST</strong>
          <span>Showing the last values received. The terminal will reconnect and request a fresh snapshot automatically.</span>
        </div>
      )}

      <div className="crypto-terminal-grid">
        <aside className="crypto-terminal-aside">
          <CryptoAssetSelector
            assets={assetsQ.data?.assets ?? []}
            selected={symbol}
            onSelect={setSymbol}
            loading={assetsQ.isLoading}
          />
        </aside>

        <div className="crypto-terminal-main">
          <CryptoSubcategoryNav active={subcategory} onChange={setSubcategory} />
          <p className="crypto-subnav-hint" id={`crypto-subpanel-${subcategory}`}>
            {subcategoryHint(subcategory)}
          </p>

          {subcategory === "ALL" && (
            <>
              <div className="crypto-tf-bar" role="tablist" aria-label="Timeframe">
                {(timeframesQ.data?.timeframes ?? []).map((tf) => {
                  const cap = timeframesQ.data?.capabilities.find((c) => c.id === tf.id);
                  return (
                    <button
                      key={tf.id}
                      role="tab"
                      aria-selected={tf.id === activeTimeframe}
                      className={tf.id === activeTimeframe ? "active" : undefined}
                      onClick={() => setTimeframe(tf.id)}
                      disabled={cap ? !cap.supported : false}
                      title={`${tf.label} · ${cap?.native ? "native" : "aggregated"} · up to ${tf.max_history_candles} candles`}
                    >
                      <span className="crypto-tf-id">{tf.label}</span>
                      <span className="crypto-tf-tag">
                        {cap?.aggregation_method === "native" ? "native" : "roll-up"}
                      </span>
                    </button>
                  );
                })}
                <span className="crypto-tf-note">
                  source interval {capability?.source_interval ?? "—"}
                  {lastMessageAt && ` · last frame ${new Date(lastMessageAt).toLocaleTimeString()}`}
                </span>
              </div>

              <CryptoLiveTicker
                symbol={symbol}
                name={selectedAsset?.name ?? symbol}
                displaySymbol={selectedAsset?.display ?? symbol}
                quote={quoteQ.data}
                liveTick={liveTick}
                loading={quoteQ.isLoading}
                error={quoteQ.isError ? (quoteQ.error as Error).message : null}
              />

              <CryptoCandleChart
                symbol={symbol}
                name={selectedAsset?.name ?? symbol}
                timeframeLabel={timeframeConfig?.label ?? activeTimeframe}
                candles={candlesQ.data?.candles ?? []}
                liveTail={liveTail}
                aggregated={candlesQ.data?.aggregated ?? capability?.aggregation_required ?? false}
                downsampled={candlesQ.data?.downsampled ?? false}
                downsampleNote={candlesQ.data?.downsample_note ?? null}
                loading={candlesQ.isLoading}
              />

              <div className="crypto-terminal-two-col">
                <CryptoMicroTrendCard
                  analytics={analyticsQ.data}
                  loading={analyticsQ.isLoading}
                  error={analyticsQ.isError ? (analyticsQ.error as Error).message : null}
                  onRetry={() => analyticsQ.refetch()}
                />
                <CryptoVolatilityCard
                  analytics={analyticsQ.data}
                  loading={analyticsQ.isLoading}
                  error={analyticsQ.isError ? (analyticsQ.error as Error).message : null}
                  onRetry={() => analyticsQ.refetch()}
                />
              </div>

              <CryptoMicroTrendChart
                candles={candlesQ.data?.candles ?? []}
                timeframeLabel={timeframeConfig?.label ?? activeTimeframe}
                trendDirection={analyticsQ.data?.trend?.direction}
                volatilityRegime={analyticsQ.data?.volatility?.regime}
                loading={candlesQ.isLoading}
              />

              <CryptoForecastPanel
                symbol={symbol}
                data={forecastQ.data}
                loading={forecastQ.isLoading}
                error={forecastQ.isError ? (forecastQ.error as Error).message : null}
                onRetry={() => forecastQ.refetch()}
                horizon={horizon}
                onHorizonChange={setHorizon}
              />

              <div className="crypto-terminal-two-col">
                <CryptoDataQualityPanel
                  quality={candlesQ.data?.quality ?? analyticsQ.data?.quality}
                  gaps={candlesQ.data?.gaps ?? analyticsQ.data?.gaps}
                  timeframeLabel={timeframeConfig?.label ?? activeTimeframe}
                />
                <CryptoAnalyticsPanel
                  analytics={analyticsQ.data}
                  loading={analyticsQ.isLoading}
                  error={analyticsQ.isError ? (analyticsQ.error as Error).message : null}
                />
              </div>

              <CryptoMultiTimeframePanel
                data={multiQ.data}
                loading={multiQ.isLoading}
                error={multiQ.isError ? (multiQ.error as Error).message : null}
                selectedTimeframe={activeTimeframe}
                onSelect={setTimeframe}
              />

              <CryptoSourcesPanel
                sources={sourcesQ.data}
                health={healthQ.data?.providers ?? sourcesQ.data?.health}
                loading={sourcesQ.isLoading}
                error={sourcesQ.isError ? (sourcesQ.error as Error).message : null}
              />
            </>
          )}

          {subcategory === "PRE-MARKET" && (
            <CryptoPreMarketView
              data={preSessionQ.data}
              loading={preSessionQ.isLoading}
              error={preSessionQ.isError ? (preSessionQ.error as Error).message : null}
              onRetry={() => preSessionQ.refetch()}
            />
          )}

          {subcategory === "INSTITUTIONS" && (
            <CryptoInstitutionsView
              symbol={symbol}
              data={institutionsQ.data}
              loading={institutionsQ.isLoading}
              error={institutionsQ.isError ? (institutionsQ.error as Error).message : null}
              onRetry={() => institutionsQ.refetch()}
            />
          )}

          {subcategory === "TARGETS" && (
            <CryptoTargetsPanel
              symbol={symbol}
              timeframe={activeTimeframe}
              data={targetsQ.data}
              loading={targetsQ.isLoading}
              error={targetsQ.isError ? (targetsQ.error as Error).message : null}
              onRetry={() => targetsQ.refetch()}
            />
          )}

          {subcategory === "INDUSTRY" && (
            <CryptoIndustryView
              data={industryQ.data}
              loading={industryQ.isLoading}
              error={industryQ.isError ? (industryQ.error as Error).message : null}
              onRetry={() => industryQ.refetch()}
            />
          )}

          <footer className="crypto-terminal-foot">
            <span>
              {candlesQ.data
                ? `${candlesQ.data.returned} candles returned · raw ${candlesQ.data.raw_count}`
                : "—"}
            </span>
            <span className={`freshness ${statusTone(analyticsQ.data?.data_status ?? candlesQ.data?.data_status)}`}>
              {analyticsQ.data?.data_status ?? candlesQ.data?.data_status ?? "UNAVAILABLE"}
            </span>
            <span className="dim">
              Source {quoteQ.data?.source ?? sourcesQ.data?.sources?.[0]?.provider ?? NA} · updated{" "}
              {quoteQ.data?.timestamp ? formatDateTime(quoteQ.data.timestamp) : NA}
            </span>
            <span className="dim">
              Real data only. Modelled figures are estimates, not guarantees — not investment advice.
            </span>
          </footer>
        </div>
      </div>
    </main>
  );
}
