from contextlib import asynccontextmanager
from datetime import date,timedelta
import asyncio
import math
import pandas as pd
from fastapi import FastAPI,HTTPException,WebSocket,WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel,Field
from typing import Optional
from .config import settings
from .logging_config import configure_logging, get_logger
from .agents import DataAgent,PredictionAgent,InsightAgent
from .lstm_agent import LSTMPredictionAgent
from .gru_agent import GRUPredictionAgent
from .ensemble import run_ensemble
from .baselines import baseline_report
from .backtest import walk_forward_backtest
from .cross_asset import cross_asset_report
from .multi_asset import ASSET_CLASSES,build_overview
from .alerts import evaluate_alerts
from .monitoring import compute_drift_report,resolve_predictions
from .llm_briefing import generate_briefing
from .security import RateLimitMiddleware,RateLimiter,validate_ticker
from .db import init_db
from . import repository as repo
from . import jobs
from .news import analyze_news
from .portfolio import portfolio_summary
from .providers import MarketDataManager,YFinanceProvider,FinnhubProvider,DataStatus,ProviderError
from . import macro as macro_mod
from . import events as events_mod
from . import fundamentals as fundamentals_mod
from . import regime as regime_mod
from . import crypto_pro as crypto_mod
from . import screener as screener_mod
from . import screener_classic as screener_classic_mod
from .screener_classic import ScreenerFilters
# Phase 4: PSX announcements/filings + rule-based AI intelligence (real feed,
# labeled analysis, clearly-simulated demo mode).
from . import announcements as announcements_mod
from .announcements import AnnouncementFiltersModel

# Configure structured logging
configure_logging(log_level="INFO")
logger=get_logger("neural_market.main")

@asynccontextmanager
async def lifespan(app:FastAPI):
    init_db()  # Phase 3: create tables on startup if they don't already exist
    # Phase 10: background maintenance loop (alert checks, prediction
    # resolution, cache/rate-limiter cleanup). Disable via BACKGROUND_JOBS_ENABLED=false.
    background_task=None
    if settings.background_jobs_enabled:
        background_task=asyncio.create_task(jobs.run_background_loop(manager,rate_limiter))
    yield
    if background_task:
        background_task.cancel()
        try: await background_task
        except asyncio.CancelledError: pass

app=FastAPI(title="Neural Market API",version="2.3.0",description="Stock analytics and educational ML forecasting API",lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=[v.strip() for v in settings.cors_origins.split(',')],allow_credentials=True,allow_methods=["*"],allow_headers=["*"])
# Phase 19: simple in-memory rate limit, per client IP. /health, /docs, /openapi stay exempt.
rate_limiter=RateLimiter(max_requests=settings.rate_limit_max_requests,window_seconds=settings.rate_limit_window_seconds)
app.add_middleware(RateLimitMiddleware,limiter=rate_limiter)

# Phase 2: provider manager. yfinance is primary; Finnhub is an optional live-quote
# fallback that only activates if FINNHUB_API_KEY is set (skipped otherwise — no
# API key is required to run the app). Add a new provider here, nowhere else,
# when onboarding another data source later.
manager=MarketDataManager(
    providers=[YFinanceProvider(max_retries=settings.provider_max_retries),FinnhubProvider(settings.finnhub_api_key)],
    history_cache_ttl=settings.history_cache_ttl_seconds,
    quote_cache_ttl=settings.quote_cache_ttl_seconds,
    profile_cache_ttl=settings.profile_cache_ttl_seconds,
    news_cache_ttl=settings.news_cache_ttl_seconds,
)
data,predictor,insighter,lstm,gru=DataAgent(manager),PredictionAgent(),InsightAgent(),LSTMPredictionAgent(),GRUPredictionAgent()

class HistoryRequest(BaseModel): start:date; end:date; interval:str="1d"
class PredictRequest(HistoryRequest): horizon:int=Field(7,ge=1,le=30); model:str="rf"; lstm_epochs:int=Field(25,ge=5,le=100)
class BacktestRequest(BaseModel): start:date; end:date; model:str="ridge"; test_days:int=Field(60,ge=10,le=250); refit_every:int=Field(5,ge=1,le=30)
class WatchlistAddRequest(BaseModel): ticker:str; note:Optional[str]=None
class CrossAssetRequest(BaseModel): tickers:list[str]; start:date; end:date; benchmark:str="SPY"
class AlertCreateRequest(BaseModel): ticker:str; alert_type:str; threshold:float
class HoldingAddRequest(BaseModel): ticker:str; shares:float=Field(...,gt=0); avg_cost:float=Field(...,ge=0); note:Optional[str]=None
class HoldingUpdateRequest(BaseModel): shares:Optional[float]=Field(None,gt=0); avg_cost:Optional[float]=Field(None,ge=0); note:Optional[str]=None
class MacroRequest(BaseModel): source:str="yfinance"; indicators:Optional[list[str]]=None; history_days:int=Field(365,ge=60,le=1825)
class EventStudyRequest(BaseModel): event_dates:list[str]; label:str="Event study"
class CryptoRequest(BaseModel): source:str="coingecko"
class ScreenerRequest(BaseModel): tickers:list[str]; lookback_days:int=Field(365,ge=90,le=1825)

SUPPORTED_ALERT_TYPES={"price_above","price_below","pct_change","rsi_overbought","rsi_oversold"}

@app.get("/")
def root(): return {"service":"Neural Market API","docs":"/docs","health":"/health"}

@app.get("/health")
def health(): return {"status":"ok"}

@app.get("/api/system/health")
def system_health():
    """Phase 2+3: real subsystem status — providers, cache, and now the database."""
    db_status="ok"
    try: repo.list_watchlist()
    except Exception as e: db_status=f"error: {e}"
    return {"status":"ok","providers":manager.provider_status(),"cache":manager.cache_stats(),"database":db_status}

@app.get("/api/stocks/{ticker}/profile")
async def profile(ticker:str):
    try:
        return await data.profile(validate_ticker(ticker))
    except Exception as e: raise HTTPException(400,str(e))

@app.get("/api/stocks/{ticker}/snapshot")
async def stock_snapshot_route(ticker:str):
 """Phase 5: one consolidated payload for the stock detail page — price,
 absolute/percent change, day range, volume, traded value, 52-week range and
 company profile — so the UI needs a single request. Every value comes from
 real provider data; a field the provider doesn't return is null, never
 invented. Unavailable tickers return a clean 4xx, not zeros."""
 try:
  ticker=validate_ticker(ticker)
  end=date.today(); start=end-timedelta(days=400)
  frame,source,status=await data.history(ticker,start,end)
  frame=frame.dropna(subset=["Close"])
  if frame.empty: raise HTTPException(404,f"No price history available for {ticker}.")

  def _f(v):
   try:
    x=float(v); return None if math.isnan(x) else round(x,4)
   except (TypeError,ValueError): return None

  last=frame.iloc[-1]
  prev=frame.iloc[-2] if len(frame)>1 else None
  price=float(last["Close"])
  prev_close=float(prev["Close"]) if prev is not None else None
  change=(price-prev_close) if prev_close is not None else None
  change_pct=((change/prev_close)*100.0) if prev_close else None
  win=frame.tail(252)
  volume=_f(last["Volume"]) if "Volume" in frame.columns else None
  profile={}
  try: profile=await data.profile(ticker)
  except Exception as e: logger.debug("snapshot profile unavailable for %s: %s",ticker,e)

  return {
   "ticker":ticker,
   "name":profile.get("name"),"sector":profile.get("sector"),"industry":profile.get("industry"),
   "country":profile.get("country"),"currency":profile.get("currency"),"exchange":profile.get("exchange"),
   "market_cap":profile.get("market_cap"),"website":profile.get("website"),"summary":profile.get("summary"),
   "price":round(price,4),
   "previous_close":round(prev_close,4) if prev_close is not None else None,
   "change":round(change,4) if change is not None else None,
   "change_percent":round(change_pct,4) if change_pct is not None else None,
   "open":_f(last["Open"]) if "Open" in frame.columns else None,
   "day_high":_f(last["High"]) if "High" in frame.columns else None,
   "day_low":_f(last["Low"]) if "Low" in frame.columns else None,
   "volume":volume,
   "traded_value":round(volume*price,2) if volume is not None else None,
   "week52_high":_f(win["High"].max()) if "High" in frame.columns else None,
   "week52_low":_f(win["Low"].min()) if "Low" in frame.columns else None,
   "last_date":str(pd.Timestamp(frame.index[-1]).date()),
   "data_meta":{"source":source,"status":status.value},
  }
 except HTTPException: raise
 except Exception as e: raise HTTPException(400,str(e))

@app.get("/api/stocks/{ticker}/news")
async def news_route(ticker:str,limit:int=10):
    """Phase 10: recent headlines + lexicon sentiment. Empty feed is a
    normal answer (aggregate all zeros), only a total provider failure is an
    error. limit is clamped so nobody can force a huge headline fetch."""
    try:
        ticker=validate_ticker(ticker)
        items,source,status=await manager.news(ticker,limit=max(1,min(int(limit),30)))
        report=analyze_news(items)
        return {**report,"meta":{"source":source,"status":status.value}}
    except Exception as e: raise HTTPException(400,str(e))

@app.post("/api/stocks/{ticker}/history")
async def history(ticker:str,body:HistoryRequest):
 try:
  ticker=validate_ticker(ticker)
  d,source,status=await data.history(ticker,body.start,body.end,body.interval)
  out=d.reset_index().rename(columns={d.index.name or "index":"date"});out.date=out.date.astype(str)
  return {"rows":out.where(out.notna(),None).to_dict("records"),"meta":{"source":source,"status":status.value}}
 except Exception as e: raise HTTPException(400,str(e))

@app.post("/api/stocks/{ticker}/predict")
async def forecast(ticker:str,body:PredictRequest):
 try:
  ticker=validate_ticker(ticker)
  d,source,status=await data.history(ticker,body.start,body.end)
  kind=body.model.lower()
  # Phase 7: rf/ridge (existing), lstm (existing), gru (new) and ensemble (new,
  # combines whichever of the above succeed) are all selectable from one field.
  if kind=="lstm": points,metrics=lstm.predict(d,body.horizon,epochs=body.lstm_epochs)
  elif kind=="gru": points,metrics=gru.predict(d,body.horizon,epochs=body.lstm_epochs)
  elif kind=="ensemble":
   points,metrics=run_ensemble(d,body.horizon,tabular_forecaster=predictor.tabular,
                                lstm_forecaster=lambda df,h:lstm.predict(df,h,epochs=body.lstm_epochs),
                                gru_forecaster=lambda df,h:gru.predict(df,h,epochs=body.lstm_epochs))
  else: points,metrics=predictor.tabular(d,body.horizon,kind)

  # Phase 6: every model is shown next to the naive baselines, never hidden even when it loses.
  baselines=baseline_report(d)
  beats_naive=metrics.get("mae",float("inf"))<baselines["naive_persistence"]["mae"]

  # Phase 3/9: persist every real prediction so future accuracy tracking is
  # based on what the app actually said, not a simulation. Never let a DB
  # hiccup break the forecast the user is waiting on.
  try:
   repo.save_prediction(ticker=ticker,model=kind,horizon=body.horizon,data_source=source,data_status=status.value,predictions=points,metrics=metrics)
  except Exception as e:
   logger.warning("failed to persist prediction (continuing anyway): %s",e)

  return {"ticker":ticker.upper(),"predictions":points,"model_metrics":metrics,"insights":insighter.make(d,points,metrics),
          "baseline_comparison":baselines,"beats_naive_baseline":beats_naive,
          "data_meta":{"source":source,"status":status.value},"disclaimer":"Educational forecast only; not investment advice."}
 except Exception as e: raise HTTPException(400,str(e))

@app.get("/api/stocks/{ticker}/predictions/history")
def prediction_history(ticker:str,limit:int=50):
 try: return repo.get_prediction_history(ticker,limit=limit)
 except Exception as e: raise HTTPException(400,str(e))

@app.post("/api/stocks/{ticker}/backtest")
async def backtest(ticker:str,body:BacktestRequest):
 """Phase 9: walk-forward backtest, not a shuffled/leaky train-test split.
 The return/drawdown/win-rate numbers assume one specific, simple default
 strategy — see backtest.py's module docstring — and are illustrative,
 not a trading recommendation."""
 try:
  ticker=validate_ticker(ticker)
  d,source,status=await data.history(ticker,body.start,body.end)
  result=walk_forward_backtest(d,model_kind=body.model.lower(),test_days=body.test_days,refit_every=body.refit_every)
  return {"ticker":ticker.upper(),"data_meta":{"source":source,"status":status.value},
          "daily":result.daily,"mae":result.mae,"rmse":result.rmse,"directional_accuracy":result.directional_accuracy,
          "total_return_pct":result.total_return_pct,"benchmark_return_pct":result.benchmark_return_pct,
          "max_drawdown_pct":result.max_drawdown_pct,"win_rate":result.win_rate,"num_trades":result.num_trades,
          "model":result.model,"refit_every":result.refit_every,"test_days":result.test_days,
          "disclaimer":"Paper/simulation only, one illustrative default strategy; not investment advice."}
 except Exception as e: raise HTTPException(400,str(e))

@app.get("/api/watchlist")
def get_watchlist():
 try: return repo.list_watchlist()
 except Exception as e: raise HTTPException(400,str(e))

@app.get("/api/watchlist/quotes")
async def watchlist_quotes_route():
 """Phase 5: saved tickers with their latest price and % change. Prices are
 fetched fresh at read time through the provider manager (never stored), and a
 ticker whose quote can't be fetched keeps a null price — never a fabricated
 number. This also resolves bare PSX symbols to their Karachi listings."""
 try:
  items=repo.list_watchlist()
  out=[]
  for it in items:
   t=it["ticker"]; price=None; change_pct=None; status="UNAVAILABLE"
   try:
    q=await manager.quote(t)
    if q.status!=DataStatus.UNAVAILABLE and not math.isnan(q.price):
     price=round(q.price,4)
     change_pct=None if q.change_percent is None else round(q.change_percent,4)
     status=q.status.value
   except Exception as e:
    logger.debug("watchlist quote failed for %s: %s",t,e)
   out.append({**it,"price":price,"change_percent":change_pct,"status":status})
  return {"items":out,"count":len(out)}
 except Exception as e: raise HTTPException(400,str(e))

@app.post("/api/watchlist")
def post_watchlist(body:WatchlistAddRequest):
 try: return repo.add_to_watchlist(body.ticker,body.note)
 except ValueError as e: raise HTTPException(409,str(e))
 except Exception as e: raise HTTPException(400,str(e))

@app.delete("/api/watchlist/{ticker}")
def delete_watchlist(ticker:str):
 if not repo.remove_from_watchlist(ticker): raise HTTPException(404,f"{ticker.upper()} is not on the watchlist.")
 return {"removed":ticker.upper()}

@app.post("/api/cross-asset/report")
async def cross_asset_route(body:CrossAssetRequest):
 """Phase 12: correlation matrix, beta, and relative strength across multiple
 tickers — computed on returns already fetched through the same Phase 2 provider
 layer, no new data source needed."""
 try:
  tickers=[validate_ticker(t) for t in body.tickers]
  if len(tickers)<2: raise HTTPException(400,"Provide at least 2 tickers to compare.")
  benchmark=validate_ticker(body.benchmark)
  all_tickers=list(dict.fromkeys(tickers+[benchmark]))  # de-duped, benchmark included
  fetched=await asyncio.gather(*(data.history(t,body.start,body.end) for t in all_tickers),return_exceptions=True)
  price_series={}
  volumes={}
  errors={}
  for t,result in zip(all_tickers,fetched):
   if isinstance(result,Exception): errors[t]=str(result)
   else:
    frame,source,status=result; price_series[t]=frame["Close"]
    if "Volume" in frame.columns: volumes[t]=frame["Volume"]
  if benchmark not in price_series: raise HTTPException(400,f"Could not fetch benchmark {benchmark}: {errors.get(benchmark,'unknown error')}")
  report=cross_asset_report(price_series,benchmark=benchmark,volumes=volumes)
  if errors: report["unavailable"]=errors
  return report
 except HTTPException: raise
 except Exception as e: raise HTTPException(400,str(e))

@app.get("/api/markets/{asset_class}")
async def markets_route(asset_class:str):
 """Phase 13: crypto/commodities/forex — reuses the same yfinance-backed
 provider manager as everything else, just with a curated symbol list."""
 try: return await build_overview(manager,asset_class)
 except ValueError as e: raise HTTPException(400,str(e))

@app.get("/api/markets")
def markets_list():
 return {"asset_classes":list(ASSET_CLASSES.keys())}

@app.post("/api/stocks/{ticker}/briefing")
async def briefing_route(ticker:str):
 """Phase 14: optional AI-generated summary — only ever narrates numbers this
 endpoint itself computed and hands to the model; reports UNAVAILABLE cleanly
 if ANTHROPIC_API_KEY isn't set, never breaks the rest of the app."""
 try:
  ticker=validate_ticker(ticker)
  d,source,status=await data.history(ticker,date.today()-timedelta(days=200),date.today())
  baselines=baseline_report(d)
  last=d.iloc[-1]
  structured={
   "ticker":ticker,"latest_close":round(float(last.Close),4),
   "rsi_14":round(float(last.rsi_14),4) if "rsi_14" in d.columns else None,
   "sma_10":round(float(last.sma_10),4) if "sma_10" in d.columns else None,
   "sma_30":round(float(last.sma_30),4) if "sma_30" in d.columns else None,
   "adx_14":round(float(last.adx_14),4) if "adx_14" in d.columns else None,
   "data_status":status.value,"data_source":source,
   "naive_baseline_mae":baselines["naive_persistence"]["mae"],
  }
  result=generate_briefing(structured,api_key=settings.anthropic_api_key,model=settings.anthropic_model)
  return {**result,"structured_data":structured}
 except Exception as e: raise HTTPException(400,str(e))

@app.post("/api/alerts")
def create_alert_route(body:AlertCreateRequest):
 try:
  ticker=validate_ticker(body.ticker)
  if body.alert_type not in SUPPORTED_ALERT_TYPES: raise HTTPException(400,f"alert_type must be one of {sorted(SUPPORTED_ALERT_TYPES)}")
  return repo.create_alert(ticker,body.alert_type,body.threshold)
 except HTTPException: raise
 except Exception as e: raise HTTPException(400,str(e))

@app.get("/api/alerts")
def list_alerts_route(ticker:Optional[str]=None,active_only:bool=False):
 return repo.list_alerts(ticker=ticker,active_only=active_only)

@app.delete("/api/alerts/{alert_id}")
def delete_alert_route(alert_id:int):
 if not repo.delete_alert(alert_id): raise HTTPException(404,"Alert not found.")
 return {"deleted":alert_id}

@app.post("/api/stocks/{ticker}/alerts/check")
async def check_alerts_route(ticker:str):
 """Phase 17: evaluates this ticker's active alerts against freshly fetched
 data (never a random/simulated trigger) and marks any that fire."""
 try:
  ticker=validate_ticker(ticker)
  active=repo.list_alerts(ticker=ticker,active_only=True)
  if not active: return {"triggered":[]}
  d,source,status=await data.history(ticker,date.today()-timedelta(days=60),date.today())
  triggered=evaluate_alerts(d,active)
  for t in triggered: repo.mark_alert_triggered(t["id"],t["current_value"])
  return {"triggered":triggered,"data_meta":{"source":source,"status":status.value}}
 except Exception as e: raise HTTPException(400,str(e))

@app.get("/api/portfolio")
async def get_portfolio_route():
    """Phase 10: portfolio positions with live market value and P&L. Current
    prices are always fetched fresh through the provider manager at read
    time — never stored — so the numbers can't go stale."""
    try:
        holdings=repo.list_holdings()
        tickers=list(dict.fromkeys(h["ticker"] for h in holdings))
        quotes:dict[str,float]={}
        for t in tickers:
            try:
                q=await manager.quote(t)
                if q.status!=DataStatus.UNAVAILABLE and not math.isnan(q.price):
                    quotes[t]=round(q.price,4)
            except Exception as e:
                logger.debug("portfolio quote failed for %s: %s",t,e)
        return portfolio_summary(holdings,quotes)
    except Exception as e: raise HTTPException(400,str(e))

@app.post("/api/portfolio")
def add_holding_route(body:HoldingAddRequest):
    try:
        ticker=validate_ticker(body.ticker)
        return repo.add_holding(ticker,body.shares,body.avg_cost,body.note)
    except HTTPException: raise
    except Exception as e: raise HTTPException(400,str(e))

@app.patch("/api/portfolio/{holding_id}")
def update_holding_route(holding_id:int,body:HoldingUpdateRequest):
    if body.shares is None and body.avg_cost is None and body.note is None:
        raise HTTPException(400,"Provide at least one field to update (shares, avg_cost, or note).")
    updated=repo.update_holding(holding_id,body.shares,body.avg_cost,body.note)
    if updated is None: raise HTTPException(404,"Holding not found.")
    return updated

@app.delete("/api/portfolio/{holding_id}")
def delete_holding_route(holding_id:int):
    if not repo.delete_holding(holding_id): raise HTTPException(404,"Holding not found.")
    return {"deleted":holding_id}

@app.post("/api/monitoring/resolve")
async def resolve_predictions_route():
 """Phase 18: for every prediction whose forecast date has passed, fetch the
 REAL close that happened and record it — never simulated, only real
 predictions the app actually made compared to real outcomes."""
 unresolved=repo.get_unresolved_predictions()
 needed:dict[tuple[str,date],Optional[float]]={}
 for record in unresolved:
  preds=record.get("predictions") or []
  if not preds: continue
  target=date.fromisoformat(preds[0]["date"])
  if target<=date.today(): needed[(record["ticker"],target)]=None
 for (ticker,target) in list(needed.keys()):
  try:
   d,_,_=await data.history(ticker,target-timedelta(days=5),target+timedelta(days=2))
   d2=d.reset_index(); date_col=d2.columns[0]; d2["_d"]=pd.to_datetime(d2[date_col]).dt.date
   match=d2[d2["_d"]==target]
   if not match.empty: needed[(ticker,target)]=float(match.iloc[0]["Close"])
  except Exception as e: logger.warning("could not resolve %s @ %s: %s",ticker,target,e)
 resolved=resolve_predictions(unresolved,actual_price_lookup=lambda t,d0:needed.get((t,d0)))
 for r in resolved: repo.set_actual_price(r["id"],r["actual_price"])
 return {"resolved_count":len(resolved),"resolved":resolved}

@app.get("/api/monitoring/drift")
def drift_route(ticker:Optional[str]=None,model:Optional[str]=None,window:int=20):
 resolved=repo.get_resolved_predictions(ticker=ticker,model=model)
 return compute_drift_report(resolved,window=window)

@app.get("/api/macro")
async def macro_route(source:Optional[str]=None,indicators:Optional[str]=None,history_days:int=365):
 """Macro intelligence dashboard. The SOURCE IS SELECTABLE — 'yfinance'
 (market proxies, zero setup) or 'fred' (official data, needs FRED_API_KEY).
 A failing source reports UNAVAILABLE with the reason; it never silently
 substitutes the other one."""
 try:
  src=(source or settings.macro_default_source).lower()
  keys=[k.strip() for k in indicators.split(",") if k.strip()] if indicators else None
  report=await macro_mod.macro_report(manager,source=src,indicators=keys,fred_api_key=settings.fred_api_key,history=history_days)
  return report
 except Exception as e: raise HTTPException(400,str(e))

@app.post("/api/stocks/{ticker}/events/study")
async def event_study_route(ticker:str,body:EventStudyRequest):
 """What did this asset ACTUALLY do after similar past events? Measured on
 real price windows around real dates — historical statistics, never a
 forecast of any future election/policy outcome."""
 try:
  ticker=validate_ticker(ticker)
  if not body.event_dates: raise HTTPException(400,"Provide at least one past event date.")
  # The window must actually COVER the events being studied. A fixed 1200-day
  # lookback made every older date unusable — including all four example dates
  # this page offers (2008–2023) — so the study rejected its own defaults with a
  # confusing "no usable event dates" instead of measuring anything. Anchor the
  # start to the earliest requested event (with a small buffer for the bar it
  # lands on), capped so a typo'd year can't ask for a century of data.
  try:
   event_days=events_mod.parse_event_dates(body.event_dates)
  except ValueError as exc:
   raise HTTPException(400,str(exc))
  today=date.today()
  earliest=min(event_days)
  if earliest>today: raise HTTPException(400,"Event dates must be in the past.")
  start=max(earliest-timedelta(days=14),date(1970,1,1))
  # Deliberately the provider frame rather than data.history(): the indicator
  # pipeline drops its first ~30 bars (indicator warm-up, add_indicators().dropna()),
  # which silently swallowed any event landing near the start of the window — and
  # this study only measures close-to-close moves, so those indicators were never used.
  try:
   frame,source,status=await manager.history(ticker,start,today)
  except ProviderError as exc:
   raise HTTPException(400,str(exc))
  d=frame[[c for c in ["Open","High","Low","Close","Volume"] if c in frame]].dropna()
  if d.empty: raise HTTPException(400,f"No price history available for {ticker} in the requested window.")
  result=events_mod.event_study(d,body.event_dates,body.label)
  stress=None
  try:
   items,_,_=await manager.news(ticker,limit=20)
   stress=events_mod.geopolitical_score(items)
  except Exception as e: logger.debug("stress score unavailable for %s: %s",ticker,e)
  return {"ticker":ticker.upper(),"event_study":events_mod.event_study_to_dict(result),
          "stress_score":stress,"data_meta":{"source":source,"status":status.value},
          "disclaimer":"Historical event statistics only — not a prediction of political outcomes or future returns."}
 except HTTPException: raise
 except Exception as e: raise HTTPException(400,str(e))

@app.get("/api/market-stress")
async def market_stress_route(ticker:Optional[str]=None):
 """Geopolitical/market stress gauge from real headline volume+sentiment.
 A risk indicator, explicitly not an outcome forecast."""
 try:
  # Use a default market index if no ticker provided
  t=ticker or "^GSPC"
  # Skip validation for market indices to avoid regex issues
  if not t.startswith("^"):
   t=validate_ticker(t)
  items,source,status=await manager.news(t,limit=30)
  stress=events_mod.geopolitical_score(items)
  return {**stress,"affected_assets":events_mod.affected_assets(stress.get("level") or ""),
          "data_meta":{"ticker":t,"source":source,"status":status.value}}
 except Exception as e: raise HTTPException(400,str(e))

@app.get("/api/stocks/{ticker}/fundamentals")
async def fundamentals_route(ticker:str):
 """Company deep-dive: valuation ratios, profitability, balance sheet,
 dividends, analyst targets, 52-week context. Missing fields are None,
 never fabricated."""
 try:
  ticker=validate_ticker(ticker)
  info=await data.profile(ticker)  # provider layer already caches profiles
  price=None
  try:
   q=await manager.quote(ticker)
   if q.status!=DataStatus.UNAVAILABLE and not math.isnan(q.price): price=q.price
  except Exception as e: logger.debug("fundamentals quote failed for %s: %s",ticker,e)
  full_info=dict(info)
  try:
   import yfinance as yf
   full_info=await asyncio.to_thread(lambda: yf.Ticker(ticker).info or info)
  except Exception as e: logger.debug("full info fetch failed for %s: %s",ticker,e)
  # Handle case where fundamentals might fail
  try:
   fundamentals_data=fundamentals_mod.build_fundamentals(full_info,price)
  except Exception as e:
   logger.warning("fundamentals calculation failed for %s: %s",ticker,e)
   fundamentals_data={"error":"Unable to calculate fundamentals","ticker":ticker.upper()}
  return {"ticker":ticker.upper(),**fundamentals_data,
          "data_meta":{"price_available":price is not None}}
 except Exception as e: raise HTTPException(400,str(e))

@app.get("/api/stocks/{ticker}/regime")
async def regime_route(ticker:str):
 """What kind of market is this asset in right now? Rule-based classification
 always; optional HMM when hmmlearn is installed. Descriptive, not predictive."""
 try:
  ticker=validate_ticker(ticker)
  d,source,status=await data.history(ticker,date.today()-timedelta(days=500),date.today())
  result=regime_mod.detect_regime(d)
  return {"ticker":ticker.upper(),**result,"data_meta":{"source":source,"status":status.value}}
 except Exception as e: raise HTTPException(400,str(e))

@app.post("/api/crypto/overview")
async def crypto_route(body:CryptoRequest):
 """Crypto dashboard with a SELECTABLE source: 'coingecko' (market cap, rank,
 supply) or 'yfinance' (existing provider layer). Never auto-substitutes."""
 try:
  return await crypto_mod.crypto_overview(manager,body.source)
 except Exception as e: raise HTTPException(400,str(e))

@app.post("/api/screener")
async def screener_route(body:ScreenerRequest):
 """Analytical ranking of real computed factors across tickers. Explicitly
 'not investment advice' — the ranking is a table, not a recommendation."""
 try:
  for t in body.tickers: validate_ticker(t)
  return await screener_mod.scan(manager,body.tickers,body.lookback_days)
 except Exception as e: raise HTTPException(400,str(e))

@app.get("/api/screener/defaults")
def screener_defaults_route():
 return {"tickers":[t.strip() for t in settings.screener_default_tickers.split(",") if t.strip()]}

@app.get("/api/screener-classic/universe")
def screener_classic_universe():
 return {"tickers":screener_classic_mod.DEFAULT_UNIVERSE,"size":len(screener_classic_mod.DEFAULT_UNIVERSE)}

@app.post("/api/screener-classic")
async def screener_classic_route(body:screener_classic_mod.ScreenerFilters):
 """Classic technical/price screener only — no fundamentals filters (P/E, market cap,
 etc.), since there's no real fundamentals data source wired up yet. Every
 filter here runs on the same real indicator pipeline the rest of the app uses."""
 try:
  universe=screener_classic_mod.DEFAULT_UNIVERSE
  end=date.today(); start=end-timedelta(days=120)
  async def fetcher(t): return await data.history(t,start,end)
  return await screener_classic_mod.run_screener(fetcher,universe,body)
 except Exception as e: raise HTTPException(400,str(e))

@app.get("/api/psx/announcements")
async def psx_announcements_route(
    source:str="company",
    event:Optional[str]=None,
    sentiment:Optional[str]=None,
    ticker:Optional[str]=None,
    company:Optional[str]=None,
    search:Optional[str]=None,
    date_from:Optional[str]=None,
    date_to:Optional[str]=None,
    page:int=1,
    page_size:int=20,
):
 """Phase 4: real PSX company announcements (ksestocks.com mirror of the
 official feed) + rule-based AI analysis clearly labeled as such. `source`
 selects 'company' (real feed) or 'simulated' (labeled demo dataset). A
 failing upstream reports UNAVAILABLE — it never fabricates filings."""
 try:
  filters=AnnouncementFiltersModel(source=source,event=event,sentiment=sentiment,ticker=ticker,
                                   company=company,search=search,date_from=date_from,date_to=date_to,
                                   page=page,page_size=page_size)
  return await announcements_mod.get_announcements_feed(filters)
 except ValueError as e: raise HTTPException(400,str(e))
 except Exception as e: raise HTTPException(400,str(e))

@app.get("/api/psx/announcements/{announcement_id}")
async def psx_announcement_detail_route(announcement_id:str,source:Optional[str]=None):
 """Permalink lookup for one announcement (used by /announcements/:id). Ids
 are deterministic hashes; we page through the requested source first, then
 the other, and 404 honestly when the id isn't in the current feed. This
 never fabricates a record to satisfy a link."""
 try:
  sources=[source] if source in ("company","simulated") else ["company","simulated"]
  for src in sources:
   page=1
   while page<=20:
    feed=await announcements_mod.get_announcements_feed(
        AnnouncementFiltersModel(source=src,page=page,page_size=50))
    for item in feed.get("items") or []:
     if item.get("id")==announcement_id:
      return {"item":item,"source":feed.get("source"),"source_status":feed.get("source_status"),
              "fetched_at":feed.get("fetched_at"),"ai_disclaimer":feed.get("ai_disclaimer"),
              "source_disclaimer":feed.get("source_disclaimer")}
    if not feed.get("has_more"): break
    page+=1
  raise HTTPException(404,"Announcement not found in the current feed — it may have rolled off the feed window.")
 except HTTPException: raise
 except ValueError as e: raise HTTPException(400,str(e))
 except Exception as e: raise HTTPException(400,str(e))

@app.websocket("/ws/stock/{ticker}")
async def stream(websocket:WebSocket,ticker:str):
    await websocket.accept()
    try:
        ticker=validate_ticker(ticker)
    except ValueError as e:
        try: await websocket.send_json({"type":"error","message":str(e)})
        except Exception: pass
        await websocket.close(); return
    try:
        while True:
            try:
                q=await manager.quote(ticker)
                price=None if math.isnan(q.price) else round(q.price,4)
                await websocket.send_json({"type":"price","ticker":q.ticker,"price":price,"source":q.source,"status":q.status.value,"timestamp":q.timestamp.isoformat()})
            except WebSocketDisconnect:
                break  # client went away — stop the loop cleanly
            except Exception as e:
                logger.debug("websocket error for %s: %s",ticker,e)
                try:
                    await websocket.send_json({"type":"error","message":str(e)})
                except Exception:
                    break  # can't reach the client anymore — sending would raise RuntimeError
            await asyncio.sleep(settings.live_poll_seconds)
    except WebSocketDisconnect: pass
