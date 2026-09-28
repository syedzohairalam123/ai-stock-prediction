/**
 * Phase 20 — `QuickOrderPanel`: the compact, context-aware paper-trading ticket.
 *
 * Composition only — every control is its own component. Behaviour:
 *
 *   * reads the active context from `usePaperOrderStore` (symbol, instrument,
 *     page, forecast linkage) so it always reflects what the user selected
 *   * reads a real quote through the shared market-data layer (spec §16) and
 *     prefers a live reading pushed in by a page that already has a socket
 *   * captures an opening snapshot once per instrument (spec §9/§15)
 *   * validates locally for instant feedback, and the server re-validates
 *     everything (spec §7/§24)
 *   * bounds the submit state so the panel can never be stuck on SUBMITTING
 *     (spec §27)
 *   * desktop right rail / tablet collapsible / mobile bottom drawer (spec §28)
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, ChevronUp, X } from "lucide-react";
import { useMediaQuery } from "../../hooks/useMediaQuery";
import {
  interpretPaperError,
  useCancelPaperOrder,
  useEvaluatePaperOrder,
  usePaperConfig,
  usePaperInstrument,
  usePaperOrders,
  usePaperPreview,
  useSubmitPaperOrder,
} from "../../hooks/usePaperTrading";
import {
  DEFAULT_PAPER_CONFIG,
  formatPaperNumber,
  getPaperUserId,
  isQuoteStale,
  referenceColumnLabel,
  validatePaperDraft,
  type PaperOrder,
  type PaperQuote,
} from "../../lib/paperTrading";
import { usePaperOrderStore } from "../../store/usePaperOrderStore";
import AmountControls from "./AmountControls";
import InstrumentHeader from "./InstrumentHeader";
import OrderPreview from "./OrderPreview";
import OrderTypeSelector from "./OrderTypeSelector";
import PaperHistory from "./PaperHistory";
import PriceInput from "./PriceInput";
import QuoteStatus from "./QuoteStatus";
import RiskInfoPanel from "./RiskInfoPanel";
import SideSelector from "./SideSelector";
import SimulationButton from "./SimulationButton";
import SimulationResultCard from "./SimulationResult";

const BREAKPOINT_DESKTOP = "(min-width: 1181px)";
const BREAKPOINT_MOBILE = "(max-width: 820px)";

/** Overlay a live reading (from an already-open socket) on top of the polled quote. */
function mergeLiveQuote(
  quote: PaperQuote | undefined,
  live: { symbol: string; price: number | null; source?: string | null; status?: string | null; timestamp?: string | null } | null,
): PaperQuote | null {
  if (!quote) return null;
  if (!live || live.symbol !== quote.symbol || live.price === null || !Number.isFinite(live.price)) return quote;
  const price = live.price as number;
  const previousClose = quote.previousClose;
  return {
    ...quote,
    price,
    timestamp: live.timestamp ?? quote.timestamp,
    source: live.source ?? quote.source,
    status: (live.status as PaperQuote["status"]) ?? quote.status,
    // A live socket reading is by definition current, so a previously stale
    // flag no longer applies to this value.
    dataMode: live.status === "LIVE" ? "LIVE" : quote.dataMode,
    stale: quote.stale && live.status !== "LIVE",
    change: previousClose !== null && previousClose !== undefined ? price - previousClose : quote.change,
    changePercent:
      previousClose !== null && previousClose !== undefined && previousClose !== 0
        ? ((price - previousClose) / previousClose) * 100
        : quote.changePercent,
  };
}

export default function QuickOrderPanel() {
  const isDesktop = useMediaQuery(BREAKPOINT_DESKTOP);
  const isMobile = useMediaQuery(BREAKPOINT_MOBILE);

  const isOpen = usePaperOrderStore((s) => s.isOpen);
  const isCollapsed = usePaperOrderStore((s) => s.isCollapsed);
  const context = usePaperOrderStore((s) => s.context);
  const closePanel = usePaperOrderStore((s) => s.closePanel);
  const setCollapsed = usePaperOrderStore((s) => s.setCollapsed);

  const side = usePaperOrderStore((s) => s.side);
  const orderType = usePaperOrderStore((s) => s.orderType);
  const amountMode = usePaperOrderStore((s) => s.amountMode);
  const amount = usePaperOrderStore((s) => s.amount);
  const limitPrice = usePaperOrderStore((s) => s.limitPrice);
  const acknowledgeStale = usePaperOrderStore((s) => s.acknowledgeStale);
  const setSide = usePaperOrderStore((s) => s.setSide);
  const setOrderType = usePaperOrderStore((s) => s.setOrderType);
  const setAmountMode = usePaperOrderStore((s) => s.setAmountMode);
  const setAmount = usePaperOrderStore((s) => s.setAmount);
  const addToAmount = usePaperOrderStore((s) => s.addToAmount);
  const setLimitPrice = usePaperOrderStore((s) => s.setLimitPrice);
  const useQuoteAsLimit = usePaperOrderStore((s) => s.useQuoteAsLimit);
  const setAcknowledgeStale = usePaperOrderStore((s) => s.setAcknowledgeStale);

  const quoteSnapshot = usePaperOrderStore((s) => s.quoteSnapshot);
  const captureSnapshot = usePaperOrderStore((s) => s.captureSnapshot);
  const liveQuote = usePaperOrderStore((s) => s.liveQuote);

  const submitState = usePaperOrderStore((s) => s.submitState);
  const submitError = usePaperOrderStore((s) => s.submitError);
  const preview = usePaperOrderStore((s) => s.preview);
  const setPreview = usePaperOrderStore((s) => s.setPreview);
  const finishSubmit = usePaperOrderStore((s) => s.finishSubmit);
  const failSubmit = usePaperOrderStore((s) => s.failSubmit);
  const lastOrder = usePaperOrderStore((s) => s.lastOrder);
  const lastResult = usePaperOrderStore((s) => s.lastResult);
  const setLastResult = usePaperOrderStore((s) => s.setLastResult);
  const clientRequestId = usePaperOrderStore((s) => s.clientRequestId);

  const [selectedOrder, setSelectedOrder] = useState<PaperOrder | null>(null);

  const configQuery = usePaperConfig();
  const config = configQuery.data ?? DEFAULT_PAPER_CONFIG;

  const symbol = isOpen ? context?.symbol ?? null : null;
  const instrumentQuery = usePaperInstrument(symbol, context?.kind, isOpen);
  const instrument = instrumentQuery.data?.instrument ?? null;
  const quote = useMemo(
    () => mergeLiveQuote(instrumentQuery.data?.quote, liveQuote),
    [instrumentQuery.data?.quote, liveQuote],
  );

  const historyQuery = usePaperOrders({ enabled: isOpen, limit: 20 });
  const previewMutation = usePaperPreview();
  const submitMutation = useSubmitPaperOrder();
  const evaluateMutation = useEvaluatePaperOrder();
  const cancelMutation = useCancelPaperOrder();

  const isForecast = quote?.quoteMode === "PROBABILITY" || instrument?.quoteMode === "PROBABILITY";
  const quoteMode = isForecast ? "PROBABILITY" : "PRICE";
  const stale = isQuoteStale(quote, config);

  const referencePrice = useMemo(() => {
    if (!quote) return null;
    if (isForecast) {
      const value = side === "NO" ? quote.probabilityNo : quote.probabilityYes;
      return value ?? null;
    }
    return quote.price ?? null;
  }, [quote, isForecast, side]);

  // ---------------------------------------------------------------- snapshot
  const capturedFor = useRef<string | null>(null);
  useEffect(() => {
    if (!isOpen || !quote || !context?.symbol) return;
    if (capturedFor.current === context.symbol) return;
    capturedFor.current = context.symbol;
    captureSnapshot(quote, side);
  }, [isOpen, quote, context?.symbol, side, captureSnapshot]);
  useEffect(() => {
    if (!isOpen) capturedFor.current = null;
  }, [isOpen]);

  // ------------------------------------------------------------ side sanity
  // The quote mode is only known once the instrument resolves, so the side can
  // briefly be a value the current instrument does not accept (e.g. BUY left
  // over from a stock ticket, on a forecast event). Correct it as soon as the
  // mode is known rather than sending an invalid side to the server.
  const sideVocabulary = isForecast ? "PROBABILITY" : "PRICE";
  useEffect(() => {
    if (!isOpen) return;
    const valid = sideVocabulary === "PROBABILITY" ? ["YES", "NO"] : ["BUY", "SELL"];
    if (!valid.includes(side)) setSide(sideVocabulary === "PROBABILITY" ? "YES" : "BUY");
  }, [isOpen, sideVocabulary, side, setSide]);

  // ------------------------------------------------------------------- gutter
  useEffect(() => {
    const shouldGutter = isOpen && isDesktop;
    document.body.classList.toggle("paper-panel-open", shouldGutter);
    return () => document.body.classList.remove("paper-panel-open");
  }, [isOpen, isDesktop]);

  // --------------------------------------------------------------- validation
  const numericAmount = useMemo(() => {
    const trimmed = amount.trim();
    if (!trimmed || !/^-?\d*(\.\d*)?$/.test(trimmed)) return null;
    const value = Number(trimmed);
    return Number.isFinite(value) ? value : null;
  }, [amount]);

  const numericLimit = useMemo(() => {
    const trimmed = limitPrice.trim();
    if (!trimmed || !/^-?\d*(\.\d*)?$/.test(trimmed)) return null;
    const value = Number(trimmed);
    return Number.isFinite(value) ? value : null;
  }, [limitPrice]);

  const clientIssues = useMemo(
    () =>
      validatePaperDraft(
        { amount, amountMode, orderType, limitPrice },
        {
          config,
          quantityPrecision: instrument?.quantityPrecision ?? 8,
          quoteMode,
          referencePrice,
          stale,
          acknowledgeStale,
          hasSymbol: Boolean(context?.symbol),
        },
      ),
    [amount, amountMode, orderType, limitPrice, config, instrument?.quantityPrecision, quoteMode, referencePrice, stale, acknowledgeStale, context?.symbol],
  );

  const issueFor = useCallback(
    (field: string) => clientIssues.find((issue) => issue.field === field)?.message ?? null,
    [clientIssues],
  );

  const blockedReason = useMemo(() => {
    if (!context?.symbol) return "Select an instrument to open a ticket.";
    if (instrumentQuery.isError) return "This instrument could not be resolved, so no simulation can be anchored.";
    if (quote && quote.dataMode === "UNAVAILABLE") {
      return "No usable quote is available right now, so no current price can be claimed.";
    }
    return null;
  }, [context?.symbol, instrumentQuery.isError, quote]);

  const canSubmit = clientIssues.length === 0 && !blockedReason && submitState !== "SUBMITTING";

  // ---------------------------------------------------------------- previewing
  const buildBody = useCallback(
    (extra: Record<string, unknown> = {}) => ({
      symbol: context?.symbol ?? "",
      kind: context?.kind,
      displayName: context?.displayName,
      currency: context?.currency ?? undefined,
      side,
      orderType,
      amount: numericAmount,
      amountMode,
      limitPrice: orderType === "LIMIT" ? numericLimit : null,
      timestamp: new Date().toISOString(),
      ...extra,
    }),
    [context?.symbol, context?.kind, context?.displayName, context?.currency, side, orderType, numericAmount, amountMode, numericLimit],
  );

  useEffect(() => {
    if (!isOpen || !context?.symbol) return;
    if (clientIssues.length > 0) {
      setPreview(null);
      return;
    }
    // Debounced so typing an amount does not fire a request per keystroke.
    const handle = window.setTimeout(() => {
      previewMutation.mutate(buildBody(), {
        onSuccess: (data) => setPreview(data.preview ?? null),
        onError: () => setPreview(null),
      });
    }, 400);
    return () => window.clearTimeout(handle);
    // `previewMutation` is a stable mutation object; re-running on every input
    // change is exactly the point here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, context?.symbol, side, orderType, numericAmount, amountMode, numericLimit, clientIssues.length, setPreview, buildBody]);

  // ------------------------------------------------------------------ submit
  const timeoutRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (timeoutRef.current) window.clearTimeout(timeoutRef.current);
    };
  }, []);

  const handleSubmit = useCallback(() => {
    if (!canSubmit) return;
    if (timeoutRef.current) window.clearTimeout(timeoutRef.current);

    // Hard bound on the SUBMITTING state: if the request never resolves (dead
    // connection), the panel resolves into an error card instead of spinning.
    timeoutRef.current = window.setTimeout(() => {
      const state = usePaperOrderStore.getState();
      if (state.submitState === "SUBMITTING") {
        failSubmit("The simulation request timed out. Nothing was sent anywhere — you can retry safely.");
      }
    }, Math.max(5, config.submitTimeoutSeconds) * 1000);

    const body = buildBody({
      clientRequestId: clientRequestId || undefined,
      userId: getPaperUserId(),
      openedSnapshot: quoteSnapshot
        ? { ...quoteSnapshot, selectedOutcome: isForecast ? side : null }
        : undefined,
      acknowledgeStale,
    });

    const { beginSubmit } = usePaperOrderStore.getState();
    beginSubmit();

    submitMutation.mutate(body, {
      onSuccess: (data) => {
        if (timeoutRef.current) window.clearTimeout(timeoutRef.current);
        finishSubmit(data.order, data.duplicate);
        setSelectedOrder(data.order);
      },
      onError: (error) => {
        if (timeoutRef.current) window.clearTimeout(timeoutRef.current);
        const { message, issues } = interpretPaperError(error);
        failSubmit(message, issues);
        // Allow an immediate retry of the same logical request.
        usePaperOrderStore.getState().startNewRequest();
      },
    });
  }, [canSubmit, buildBody, clientRequestId, quoteSnapshot, isForecast, side, acknowledgeStale, config.submitTimeoutSeconds, failSubmit, finishSubmit, submitMutation]);

  const handleEvaluate = useCallback(
    (orderId: string) => {
      evaluateMutation.mutate(orderId, {
        onSuccess: (data) => {
          setLastResult(data.order, data.result);
          setSelectedOrder(data.order);
        },
      });
    },
    [evaluateMutation, setLastResult],
  );

  const handleCancel = useCallback(
    (orderId: string) => {
      cancelMutation.mutate(
        { orderId, reason: "Cancelled from the quick order ticket" },
        { onSuccess: (data) => setSelectedOrder(data.order) },
      );
    },
    [cancelMutation],
  );

  if (!isOpen) return null;

  const cardOrder = selectedOrder ?? lastOrder;
  const cardResult = lastResult && cardOrder && lastResult.orderId === cardOrder.id ? lastResult : null;

  return (
    <aside
      className={`paper-ticket${isMobile ? " is-mobile" : isDesktop ? " is-desktop" : " is-tablet"}${isCollapsed ? " collapsed" : ""}`}
      aria-label="Quick order paper simulation ticket"
      role="complementary"
    >
      <header className="paper-ticket-head">
        <div className="paper-ticket-title">
          <span className="paper-ticket-badge">PAPER</span>
          <h2>Quick Order</h2>
        </div>
        <div className="paper-ticket-actions">
          {!isMobile && (
            <button
              type="button"
              className="paper-icon-button"
              aria-label={isCollapsed ? "Expand the paper ticket" : "Collapse the paper ticket"}
              aria-expanded={!isCollapsed}
              onClick={() => setCollapsed(!isCollapsed)}
            >
              {isCollapsed ? <ChevronUp size={16} aria-hidden /> : <ChevronDown size={16} aria-hidden />}
            </button>
          )}
          <button type="button" className="paper-icon-button" aria-label="Close the paper ticket" onClick={closePanel}>
            <X size={16} aria-hidden />
          </button>
        </div>
      </header>

      <div className="paper-ticket-banner" role="note">
        PAPER SIMULATION — NOT A REAL ORDER
      </div>

      {!isCollapsed && (
        <div className="paper-ticket-body">
          <InstrumentHeader
            instrument={instrument}
            quote={quote}
            config={config}
            loading={instrumentQuery.isLoading}
          />

          {blockedReason && (
            <p className="paper-blocked" role="alert">
              {blockedReason}
            </p>
          )}

          {instrumentQuery.isError && (
            <p className="paper-error" role="alert">
              {interpretPaperError(instrumentQuery.error).message}
            </p>
          )}

          <div className="paper-form">
            <SideSelector value={side} onChange={setSide} quoteMode={quoteMode} disabled={submitState === "SUBMITTING"} />
            <OrderTypeSelector
              value={orderType}
              onChange={setOrderType}
              quoteMode={quoteMode}
              disabled={submitState === "SUBMITTING"}
            />
            <AmountControls
              amount={amount}
              onChange={setAmount}
              onAdd={addToAmount}
              amountMode={amountMode}
              onModeChange={setAmountMode}
              currency={instrument?.currency ?? quote?.currency ?? null}
              quantityPrecision={instrument?.quantityPrecision ?? 8}
              disabled={submitState === "SUBMITTING"}
              error={issueFor("amount")}
            />
            <PriceInput
              referencePrice={referencePrice}
              referenceLabel={referenceColumnLabel(quoteMode)}
              quoteMode={quoteMode}
              orderType={orderType}
              limitPrice={limitPrice}
              onLimitChange={setLimitPrice}
              onUseObserved={useQuoteAsLimit}
              stale={stale}
              disabled={submitState === "SUBMITTING"}
              error={issueFor("limitPrice")}
            />

            {stale && (
              <label className="paper-stale-ack">
                <input
                  type="checkbox"
                  checked={acknowledgeStale}
                  onChange={(event) => setAcknowledgeStale(event.target.checked)}
                />
                I understand this reading is stale and am recording the simulation anyway.
              </label>
            )}

            {submitError && (
              <p className="paper-error" role="alert">
                {submitError}
              </p>
            )}

            {clientIssues.length > 0 && (
              <ul className="paper-issues" role="alert">
                {clientIssues
                  .filter((issue) => issue.code !== "stale_quote")
                  .map((issue) => (
                    <li key={`${issue.field}-${issue.code}`}>
                      <strong>{issue.field}</strong> — {issue.message}
                    </li>
                  ))}
              </ul>
            )}

            <SimulationButton
              onClick={handleSubmit}
              submitting={submitState === "SUBMITTING"}
              disabled={!canSubmit}
              blockedReason={blockedReason}
            />

            {preview && <OrderPreview preview={preview} />}
          </div>

          {cardOrder && (
            <SimulationResultCard
              order={cardOrder}
              result={cardResult}
              onEvaluate={() => handleEvaluate(cardOrder.id)}
              evaluating={evaluateMutation.isPending}
              onCancel={() => handleCancel(cardOrder.id)}
              cancelling={cancelMutation.isPending}
            />
          )}

          {(evaluateMutation.isError || cancelMutation.isError) && (
            <p className="paper-error" role="alert">
              {interpretPaperError(evaluateMutation.error ?? cancelMutation.error).message}
            </p>
          )}

          <RiskInfoPanel
            quote={quote}
            config={config}
            snapshot={quoteSnapshot}
            openingProbability={
              isForecast
                ? side === "NO"
                  ? quoteSnapshot?.probabilityNo ?? null
                  : quoteSnapshot?.probabilityYes ?? null
                : null
            }
            currentProbability={isForecast ? referencePrice : null}
          />

          <QuoteStatus quote={quote} config={config} />

          <PaperHistory
            data={historyQuery.data}
            loading={historyQuery.isLoading}
            error={historyQuery.isError ? interpretPaperError(historyQuery.error).message : null}
            activeSymbol={context?.symbol ?? null}
            onSelect={(order) => setSelectedOrder(order)}
          />

          <footer className="paper-ticket-foot">
            <span>
              Simulated value: {formatPaperNumber(numericAmount, 2)} · {amountMode === "NOTIONAL" ? "notional" : "units"}
            </span>
            <span>No real-money execution, deposits, withdrawals or payouts exist in this terminal.</span>
          </footer>
        </div>
      )}
    </aside>
  );
}
