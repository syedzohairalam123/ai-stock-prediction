from contextlib import asynccontextmanager
from datetime import date,datetime,timedelta,timezone
import asyncio
import math
import re
import pandas as pd
from sqlalchemy import and_,desc,func,or_
from fastapi import FastAPI,HTTPException,Response,WebSocket,WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel,Field
from typing import Optional
from .config import settings
from .models import NewsArticle
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
from .db import init_db,session_scope
from . import repository as repo
from . import jobs
from .news import analyze_news
from .portfolio import portfolio_summary
from .providers import MarketDataManager,YFinanceProvider,FinnhubProvider,DataStatus,ProviderError
from .providers import fx_rates
from . import macro as macro_mod
from . import forex as forex_mod
from . import commodities_pk as commodities_mod
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
from . import news_service as news_svc
from . import news_analytics
from .news_sources import FEEDS as NEWS_FEEDS, enabled_feeds as news_enabled_feeds
from .news_service import get_news_service
from . import popular_stocks as popular_stocks_mod
# Phase 10: AI Financial Assistant
from . import ai_controller

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

# Phase 10: AI Financial Assistant router
app.include_router(ai_controller.router)

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
class WatchlistReorderRequest(BaseModel): ids:list[int]
class WatchlistNoteRequest(BaseModel): note:Optional[str]=None
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
    cache=manager.cache_stats()
    # Phase 7 caches (forex / daily currency rates) live outside the stock manager.
    cache.update(fx_rates.cache_sizes())
    return {"status":"ok","providers":manager.provider_status(),"cache":cache,"database":db_status}

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

# Phase 9: watchlist ordering + notes (spec C/D — WatchlistItem{id,userId,symbol,
# addedAt,notes,sortOrder}; Add/Remove/Exists/List/Reorder engine)

@app.post("/api/watchlist/reorder")
def reorder_watchlist_route(body:WatchlistReorderRequest):
 """Persist a manual display order (sort_order 1..n in list order)."""
 try:
  if not body.ids: raise HTTPException(400,"Provide the full ordered list of watchlist ids.")
  return {"items":repo.reorder_watchlist(body.ids)}
 except HTTPException: raise
 except Exception as e: raise HTTPException(400,str(e))

@app.patch("/api/watchlist/{ticker}")
def watchlist_note_route(ticker:str,body:WatchlistNoteRequest):
 """Set or clear the personal note on a watchlist item."""
 try:
  updated=repo.update_watchlist_note(ticker,body.note)
  if updated is None: raise HTTPException(404,f"{ticker.upper()} is not on the watchlist.")
  return updated
 except HTTPException: raise
 except Exception as e: raise HTTPException(400,str(e))

@app.get("/api/watchlist/exists/{ticker}")
def watchlist_exists_route(ticker:str):
 """O(1) existence check for the watchlist action buttons."""
 try:
  items=repo.list_watchlist()
  found=next((i for i in items if i["ticker"]==ticker.upper()),None)
  return {"exists":found is not None,"item":found}
 except Exception as e: raise HTTPException(400,str(e))

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

# ---------------------------------------------------------------------------
# Phase 7 — Advanced Forex & Commodities Market Data Center
#
# Real, keyless sources only: Yahoo (live FX bid/ask + COMEX front-month metal
# futures) as primary, ExchangeRate-API's open daily feed as the labelled
# fallback. Nothing here is simulated — a pair no source can price comes back
# UNAVAILABLE with the reason attached.
# ---------------------------------------------------------------------------

@app.get("/api/forex")
async def forex_route(currencies:Optional[str]=None,refresh:bool=False):
 """PKR-based forex grid: 8 pairs with real bid/ask/mid/spread, data mode and freshness."""
 try:
  wanted=[c.strip().upper() for c in currencies.split(",") if c.strip()] if currencies else None
  payload=await forex_mod.build_forex_quotes(wanted,force_refresh=refresh)
  live=payload.get("live_count",0)
  total=payload.get("count",0)
  status="LIVE" if live and live==total else ("DELAYED" if any(q["data_mode"]=="DELAYED" for q in payload["quotes"]) else "UNAVAILABLE")
  return {**payload,"data_meta":{"source":",".join(payload.get("sources") or []) or "none","status":status}}
 except HTTPException: raise
 except Exception as e:
  logger.exception("forex route failed")
  raise HTTPException(502,f"Forex data unavailable: {str(e)[:200]}")

async def _forex_one(base_currency:str,quote_currency:str,refresh:bool):
 """Shared body for the one-pair routes. Only PKR-quoted pairs exist here, so
 anything else is a clear 400 rather than a confusing 404."""
 if quote_currency!=forex_mod.QUOTE_CURRENCY:
  raise HTTPException(400,f"Only {forex_mod.QUOTE_CURRENCY}-quoted pairs are available — use e.g. {base_currency}/{forex_mod.QUOTE_CURRENCY}.")
 payload=await forex_mod.build_single_quote(base_currency,force_refresh=refresh)
 if payload is None: raise HTTPException(404,f"No quote available for {base_currency}/{quote_currency}.")
 return payload

@app.get("/api/forex/{base}/{quote}")
async def forex_pair_route(base:str,quote:str,refresh:bool=False):
 """One pair in pair notation, e.g. /api/forex/USD/PKR."""
 try: b,q=forex_mod.parse_pair(f"{base}/{quote}")
 except ValueError as e: raise HTTPException(400,str(e))
 return await _forex_one(b,q,refresh)

@app.get("/api/forex/{symbol}")
async def forex_single_route(symbol:str,refresh:bool=False):
 """One pair as a single segment, e.g. /api/forex/USDPKR or /api/forex/USD-PKR."""
 try: b,q=forex_mod.parse_pair(symbol)
 except ValueError as e: raise HTTPException(400,str(e))
 return await _forex_one(b,q,refresh)

@app.get("/api/commodities")
async def commodities_route(refresh:bool=False):
 """PKR precious metals — Gold 24K/22K, Silver, Platinum — each unit stated explicitly."""
 try:
  payload=await commodities_mod.build_commodity_quotes(manager,force_refresh=refresh)
  priced=payload.get("priced_count",0)
  return {**payload,"data_meta":{"source":"yfinance","status":"LIVE" if priced else "UNAVAILABLE"}}
 except HTTPException: raise
 except Exception as e:
  logger.exception("commodities route failed")
  raise HTTPException(502,f"Commodity data unavailable: {str(e)[:200]}")

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

# Phase 9: Professional Portfolio & Transaction Management

class TransactionCreateRequest(BaseModel):
    symbol: str
    transaction_type: str  # BUY or SELL
    quantity: float = Field(..., gt=0)
    price: float = Field(..., gt=0)
    fees: float = Field(default=0.0, ge=0)
    transaction_date: str  # ISO date string
    notes: Optional[str] = None
    broker: Optional[str] = None
    account: Optional[str] = None

@app.post("/api/portfolio/transactions")
def create_transaction_route(body: TransactionCreateRequest):
    """Create a new BUY or SELL transaction."""
    try:
        from datetime import datetime
        from .portfolio_engine import validate_transaction, calculate_positions_weighted_average
        
        # Validate inputs
        symbol = validate_ticker(body.symbol)
        tx_type = body.transaction_type.upper()
        
        if tx_type not in ["BUY", "SELL"]:
            raise HTTPException(400, f"Invalid transaction type: {tx_type}. Must be BUY or SELL.")
        
        # Parse date
        try:
            tx_date = datetime.fromisoformat(body.transaction_date.replace('Z', '+00:00'))
        except ValueError:
            raise HTTPException(400, f"Invalid date format: {body.transaction_date}. Use ISO format.")
        
        # For SELL, validate against current positions
        if tx_type == "SELL":
            transactions = repo.list_transactions(symbol=symbol)
            if transactions:
                positions = calculate_positions_weighted_average(transactions)
                current_pos = positions.get(symbol)
                
                is_valid, error_msg = validate_transaction(
                    symbol, tx_type, body.quantity, body.price, body.fees, current_pos, tx_date=tx_date
                )
                
                if not is_valid:
                    raise HTTPException(400, error_msg)
            else:
                raise HTTPException(400, f"No position exists for {symbol}. Cannot sell.")
        else:
            # BUY still gets full field validation (finite numbers, past date)
            is_valid, error_msg = validate_transaction(
                symbol, tx_type, body.quantity, body.price, body.fees, None, tx_date=tx_date
            )
            if not is_valid:
                raise HTTPException(400, error_msg)
        
        # Create transaction
        tx = repo.create_transaction(
            symbol=symbol,
            transaction_type=tx_type,
            quantity=body.quantity,
            price=body.price,
            fees=body.fees,
            transaction_date=tx_date,
            notes=body.notes,
            broker=body.broker,
            account=body.account
        )
        
        return tx
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Transaction creation failed: {e}")
        raise HTTPException(500, f"Transaction creation failed: {str(e)}")

@app.get("/api/portfolio/transactions")
def list_transactions_route(
    symbol: Optional[str] = None,
    transaction_type: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 500
):
    """List transactions with optional filtering — BUY/SELL, symbol and an
    inclusive date range (spec M). Invalid dates are rejected, not ignored."""
    try:
        if date_from is not None:
            from datetime import datetime as _dt
            try: _dt.fromisoformat(date_from)
            except ValueError: raise HTTPException(400, f"Invalid date_from: {date_from}. Use ISO format (YYYY-MM-DD).")
        if date_to is not None:
            from datetime import datetime as _dt
            try: _dt.fromisoformat(date_to)
            except ValueError: raise HTTPException(400, f"Invalid date_to: {date_to}. Use ISO format (YYYY-MM-DD).")
        if transaction_type is not None and transaction_type.upper() not in ("BUY", "SELL"):
            raise HTTPException(400, "transaction_type must be BUY or SELL")

        txs = repo.list_transactions(
            symbol=symbol.upper() if symbol else None,
            transaction_type=transaction_type,
            date_from=date_from,
            date_to=date_to,
            limit=limit
        )
        return {"transactions": txs, "count": len(txs)}
    except HTTPException: raise
    except Exception as e:
        raise HTTPException(500, f"Failed to list transactions: {str(e)}")

@app.get("/api/portfolio/transactions/{transaction_id}")
def get_transaction_route(transaction_id: int):
    """Get a single transaction by ID."""
    tx = repo.get_transaction(transaction_id)
    if not tx:
        raise HTTPException(404, "Transaction not found")
    return tx

@app.delete("/api/portfolio/transactions/{transaction_id}")
def delete_transaction_route(transaction_id: int):
    """Delete a transaction."""
    if not repo.delete_transaction(transaction_id):
        raise HTTPException(404, "Transaction not found")
    return {"deleted": transaction_id}

@app.get("/api/portfolio/positions")
async def get_positions_route(method: str = "weighted_average"):
    """Calculate current positions from transactions with real-time prices."""
    try:
        from .portfolio_engine import (
            calculate_positions_weighted_average,
            calculate_positions_fifo,
            calculate_portfolio_summary
        )
        
        # Get all transactions
        transactions = repo.list_transactions()
        
        if not transactions:
            return {
                "positions": [],
                "summary": {
                    "num_positions": 0,
                    "total_cost_basis": 0.0,
                    "total_market_value": 0.0,
                    "total_realized_pnl": 0.0,
                    "total_unrealized_pnl": 0.0,
                    "total_pnl": 0.0,
                    "total_return_pct": 0.0
                },
                "method": method
            }
        
        # Calculate positions based on method
        if method.lower() == "fifo":
            positions = calculate_positions_fifo(transactions)
        else:
            positions = calculate_positions_weighted_average(transactions)
        
        # Get current prices
        symbols = list(positions.keys())
        current_prices = {}
        quote_status = {}
        
        for symbol in symbols:
            try:
                q = await manager.quote(symbol)
                if q.status != DataStatus.UNAVAILABLE and not math.isnan(q.price):
                    current_prices[symbol] = round(q.price, 4)
                    quote_status[symbol] = {"source": q.source, "status": q.status.value}
                else:
                    quote_status[symbol] = {"source": q.source, "status": q.status.value}
            except Exception as e:
                logger.debug(f"Failed to get price for {symbol}: {e}")
                quote_status[symbol] = {"source": "none", "status": "UNAVAILABLE"}
        
        # Calculate portfolio summary
        summary = calculate_portfolio_summary(positions, current_prices)
        summary["method"] = method
        # Phase 9 spec I/S: per-symbol provenance so the UI can show exactly
        # which positions have no live price ("PRICE UNAVAILABLE") and why.
        summary["price_status"] = quote_status
        
        return summary
        
    except Exception as e:
        logger.error(f"Position calculation failed: {e}")
        raise HTTPException(500, f"Position calculation failed: {str(e)}")

@app.get("/api/portfolio/summary")
async def get_portfolio_summary_route():
    """Get comprehensive portfolio summary with performance metrics."""
    try:
        from .portfolio_engine import calculate_positions_weighted_average, calculate_portfolio_summary
        
        # Get transactions
        transactions = repo.list_transactions()
        
        if not transactions:
            return {
                "positions": [],
                "summary": {
                    "num_positions": 0,
                    "total_cost_basis": 0.0,
                    "total_market_value": 0.0,
                    "total_realized_pnl": 0.0,
                    "total_unrealized_pnl": 0.0,
                    "total_pnl": 0.0,
                    "total_return_pct": 0.0
                },
                "disclaimer": "Portfolio tracking for education/simulation only, not investment advice."
            }
        
        # Calculate positions
        positions = calculate_positions_weighted_average(transactions)
        
        # Get current prices
        symbols = list(positions.keys())
        current_prices = {}
        quote_status = {}
        
        for symbol in symbols:
            try:
                q = await manager.quote(symbol)
                if q.status != DataStatus.UNAVAILABLE and not math.isnan(q.price):
                    current_prices[symbol] = round(q.price, 4)
                    quote_status[symbol] = {"source": q.source, "status": q.status.value}
                else:
                    quote_status[symbol] = {"source": q.source, "status": q.status.value}
            except Exception as e:
                logger.debug(f"Failed to get price for {symbol}: {e}")
                quote_status[symbol] = {"source": "none", "status": "UNAVAILABLE"}
        
        # Calculate summary
        result = calculate_portfolio_summary(positions, current_prices)
        result["price_status"] = quote_status
        result["disclaimer"] = "Portfolio tracking for education/simulation only, not investment advice."
        
        return result
        
    except Exception as e:
        logger.error(f"Portfolio summary failed: {e}")
        raise HTTPException(500, f"Portfolio summary failed: {str(e)}")

# ---------------------------------------------------------------------------
# Phase 9 (ext): Portfolio Performance — equity curve + risk metrics computed
# from REAL transactions and REAL daily closes through the provider layer.
# Nothing here is simulated: every point on the curve is a settlement close,
# and every metric is derived from that curve (or the transaction cash flows).
# ---------------------------------------------------------------------------

@app.get("/api/portfolio/performance")
async def get_portfolio_performance_route(days: int = 180):
    """Portfolio equity curve and risk-adjusted performance metrics.

    Method: the day-by-day share count is replayed from the transaction log,
    multiplied by each symbol's REAL daily closes (provider layer), and summed
    into one portfolio value series. Cash-flow timing (BUY = -cost, SELL =
    +proceeds) feeds IRR; the value series feeds CAGR, volatility, Sharpe,
    Sortino and Max Drawdown.
    """
    try:
        import pandas as pd
        from datetime import timedelta
        from .portfolio_engine import (
            calculate_irr, calculate_cagr, calculate_sharpe_ratio,
            calculate_max_drawdown,
        )

        days = max(7, min(int(days), 730))
        transactions = repo.list_transactions(limit=2000)
        if not transactions:
            return {
                "points": [], "metrics": {}, "cash_flows": 0,
                "message": "No transactions yet — add BUY/SELL entries to see performance.",
            }

        # repository rows carry transaction_date as an ISO string — parse once
        def _tx_dt(t: dict) -> datetime:
            raw = t["transaction_date"]
            return raw if isinstance(raw, datetime) else datetime.fromisoformat(str(raw))

        txs = sorted(transactions, key=lambda t: (_tx_dt(t), t.get("id") or 0))
        symbols = sorted({str(t["symbol"]).upper() for t in txs})

        end = date.today()
        start = min(end - timedelta(days=days), _tx_dt(txs[0]).date())

        # --- one real daily-close series per held symbol (provider layer) ---
        closes: dict[str, pd.Series] = {}
        failed: list[str] = []
        for sym in symbols:
            try:
                frame, _src, _st = await manager.history(sym, start, end)
                close = frame["Close"].dropna() if "Close" in frame.columns else pd.Series(dtype=float)
                if close.empty:
                    failed.append(sym)
                else:
                    closes[sym] = close
            except Exception as e:
                logger.debug("performance history failed for %s: %s", sym, e)
                failed.append(sym)

        if not closes:
            return {
                "points": [], "metrics": {},
                "unavailable_symbols": failed,
                "message": "Daily closes unavailable from all providers — no curve can be drawn (no fake prices are used).",
            }

        # --- replay share counts day by day, price with real closes ---
        busdays = pd.bdate_range(start, end)
        tx_df = pd.DataFrame([{
            "date": pd.Timestamp(_tx_dt(t)).normalize(),
            "symbol": str(t["symbol"]).upper(),
            "signed": (float(t["quantity"]) if str(t["transaction_type"]).upper() == "BUY"
                       else -float(t["quantity"])),
            # BUY = money out (negative), SELL = money in (positive, net of fees)
            "cash": (-(float(t["quantity"]) * float(t["price"]) + float(t.get("fees") or 0.0))
                     if str(t["transaction_type"]).upper() == "BUY"
                     else (float(t["quantity"]) * float(t["price"]) - float(t.get("fees") or 0.0))),
        } for t in txs])

        qty = {s: 0.0 for s in symbols}
        cash_flows: list[tuple[datetime, float]] = []
        tx_iter = 0
        points: list[dict] = []
        values: list[float] = []

        for day in busdays:
            while tx_iter < len(tx_df) and tx_df.iloc[tx_iter]["date"] <= day:
                row = tx_df.iloc[tx_iter]
                if row["symbol"] in closes:      # unpriced symbols can't be valued
                    qty[row["symbol"]] += row["signed"]
                    cash_flows.append((row["date"].to_pydatetime(), float(row["cash"])))
                tx_iter += 1

            total = 0.0
            for sym, series in closes.items():
                s = series[series.index <= day]
                if s.empty or qty[sym] <= 0:
                    continue
                total += qty[sym] * float(s.iloc[-1])
            values.append(total)
            points.append({"date": day.strftime("%Y-%m-%d"), "value": round(total, 2)})

        # drop leading zero days (before the first priced transaction)
        first_active = next((i for i, v in enumerate(values) if v > 0), None)
        if first_active is not None:
            points = points[first_active:]
            values = values[first_active:]

        # --- metrics from the real curve + real cash flows ---
        metrics: dict = {}
        if len(values) >= 2:
            s = pd.Series(values, dtype=float)
            daily_returns = s.pct_change().dropna()
            invested = -sum(cf for _d, cf in cash_flows if cf < 0)  # buys are negative flows
            realized = sum(cf for _d, cf in cash_flows if cf > 0)   # sell proceeds, net of fees
            current_value = values[-1]
            irr = calculate_irr(cash_flows, current_value, datetime.combine(end, datetime.min.time()))
            years = max((busdays[-1] - busdays[0]).days / 365.25, 1e-9)
            net = current_value + realized - invested
            metrics = {
                "current_value": round(current_value, 2),
                "invested_capital": round(invested, 2),
                "realized_proceeds": round(realized, 2),
                "net_pnl": round(net, 2),
                "net_return_pct": round(net / invested * 100, 2) if invested > 0 else None,
                "irr_pct": irr,
                "cagr_pct": calculate_cagr(invested, current_value + realized, years),
                "volatility_pct": round(float(daily_returns.std() * (252 ** 0.5) * 100), 2)
                                  if len(daily_returns) > 1 else None,
                "sharpe_ratio": calculate_sharpe_ratio(daily_returns.tolist())
                                if len(daily_returns) > 1 else None,
                "sortino_ratio": (
                    round(float((daily_returns.mean() * 252 - 0.02)
                                / (downside.std() * (252 ** 0.5))), 2)
                    if len(daily_returns) > 1 and (downside := daily_returns[daily_returns < 0]) is not None
                    and len(downside) > 0 and downside.std() > 0 else None
                ),
                "max_drawdown_pct": calculate_max_drawdown(values)[0],
            }

        return {
            "points": points,
            "metrics": metrics,
            "cash_flows": len(cash_flows),
            "unavailable_symbols": failed,
            "start": start.isoformat(),
            "end": end.isoformat(),
        }
    except Exception as e:
        logger.error(f"Portfolio performance failed: {e}")
        raise HTTPException(500, f"Portfolio performance failed: {str(e)}")

# Phase 9: Popular Stocks Discovery

@app.get("/api/stocks/popular")
async def get_popular_stocks_route(category: Optional[str] = None, limit: int = 20):
    """Get popular PSX stocks with real market data and trends."""
    try:
        result = await popular_stocks_mod.get_popular_stocks(manager, category, limit)
        return result
    except Exception as e:
        logger.error(f"Popular stocks fetch failed: {e}")
        raise HTTPException(500, f"Failed to fetch popular stocks: {str(e)}")

@app.get("/api/stocks/categories")
def get_stock_categories_route():
    """Get available stock categories."""
    try:
        return {"categories": popular_stocks_mod.get_stock_categories()}
    except Exception as e:
        raise HTTPException(500, f"Failed to fetch categories: {str(e)}")

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

# Phase 8: Professional News & Financial Intelligence Desk
# Real news aggregation from multiple sources with filtering, search, and ticker linking

class NewsFiltersModel(BaseModel):
    """News filtering parameters.

    `sort` chooses between pure recency and the two real signals the analytics
    layer computes — relevance (BM25 against the query) and impact (the
    transparent 0-100 score). Default stays `recent`, which is what a news feed
    should do when nobody asked for anything else.
    """
    category: Optional[str] = None
    publisher: Optional[str] = None
    symbol: Optional[str] = None
    event_type: Optional[str] = None
    priority: Optional[str] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    search: Optional[str] = None
    sort: str = Field("recent", pattern="^(recent|impact|relevance)$")
    min_impact: Optional[float] = Field(None, ge=0, le=100)
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=5, le=100)


def _news_item(article, *, full: bool = False) -> dict:
    """One article serialized for the API.

    Written once so every news endpoint returns the *same* shape — a client
    should never have to care which route produced an article. `full=True` adds
    the body/analytics fields only the detail view needs.
    """
    item = {
        "id": article.id,
        "title": article.title,
        "slug": article.slug,
        "publisher": article.publisher,
        "author": article.author,
        "published_at": article.published_at.isoformat() if article.published_at else None,
        "image_url": article.image_url,
        "excerpt": article.excerpt,
        "category": article.category,
        "tags": article.tags or [],
        "related_symbols": [s for s in (article.related_symbols or [])],
        "related_indices": article.related_indices or [],
        "topics": getattr(article, "topics", None) or [],
        "keywords": getattr(article, "keywords", None) or [],
        "entities": getattr(article, "entities", None) or [],
        "event_type": getattr(article, "event_type", None),
        "impact_score": getattr(article, "impact_score", None),
        "reading_time_minutes": getattr(article, "reading_time_minutes", None),
        "word_count": getattr(article, "word_count", None),
        "source_url": article.source_url,
        "source_type": article.source_type,
        "priority": article.priority,
        "data_source": article.data_source,
        # Spec K: when an item is not live, the UI must be able to say so
        # without guessing — the mode is computed from the publisher's own
        # timestamp at ingest time, never from the fetch time.
        "data_mode": getattr(article, "data_mode", None) or "UNKNOWN",
        "sentiment": {
            "score": article.sentiment_score,
            "label": article.sentiment_label,
        },
    }
    if full:
        item["content"] = article.content
        item["created_at"] = article.created_at.isoformat() if article.created_at else None
        item["updated_at"] = article.updated_at.isoformat() if article.updated_at else None
        item["feed_key"] = getattr(article, "feed_key", None)
    return item


def _news_pagination(page: int, page_size: int, total: int) -> dict:
    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": (total + page_size - 1) // page_size if page_size else 0,
    }

@app.post("/api/news/refresh")
async def refresh_news(query: str = "Pakistan stock market", symbol: str = "",
                      region: Optional[str] = None, include_rss: bool = True):
    """Ingest fresh news from every configured source and store it.

    Runs automatically in the background loop; this route triggers it on demand
    (the Refresh button on the news page). Sources without credentials
    contribute nothing rather than failing the request, and the response says
    exactly which feeds answered and what each returned.
    """
    try:
        news_service = get_news_service()
        sources = (["rss", "symbols"] if include_rss else []) + ["newsapi", "finnhub", "alpha_vantage"]
        with session_scope() as db:
            count = await news_service.aggregate_and_store(
                db,
                sources=sources,
                query=query,
                symbol=symbol,
                region=region,
            )
            total = db.query(func.count(NewsArticle.id)).scalar() or 0
        statuses = news_service.source_status()
        return {
            "success": True,
            "articles_stored": count,
            "total_articles": int(total),
            "message": f"Fetched and stored {count} new articles",
            "sources": statuses,
            "sources_ok": sum(1 for s in statuses if s.get("status") == "OK"),
            "ingested_at": (news_service.last_ingest_at or datetime.now(timezone.utc)).isoformat(),
        }
    except Exception as e:
        logger.error(f"News refresh failed: {e}")
        raise HTTPException(500, f"Failed to refresh news: {str(e)}")

#: Characters that make two spellings of the same financial term differ:
#: `kse100`/`KSE-100`, `s&p500`/`S&P 500`, `d.g. khan`/`DG Khan`.
_SEARCH_SEPARATORS = ("-", " ", "&", ".", "'", "/", ",")


def _normalized_column(column):
    """Lower-cased column with every separator removed, in SQL.

    Doing the normalisation on both sides of the comparison is what makes a
    search for ``kse100`` find ``KSE-100`` without storing a second, redundant
    copy of every headline.
    """
    expression = func.lower(column)
    for separator in _SEARCH_SEPARATORS:
        expression = func.replace(expression, separator, "")
    return expression


def _news_text_condition(search: str):
    """SQL condition matching `search` against headline, lede and body.

    A plain substring test gets the most common financial-search case wrong:
    ``kse100`` must find ``KSE-100``. So two variants are OR'd — the literal
    phrase, and a separator-insensitive form compared against a
    separator-stripped column. Nothing extra is stored; it is a normalisation
    applied at query time.
    """
    raw = f"%{search.strip()}%"
    normalized = re.sub(r"[^a-z0-9]+", "", search.lower())

    conditions = [
        NewsArticle.title.ilike(raw),
        NewsArticle.excerpt.ilike(raw),
        NewsArticle.content.ilike(raw),
    ]
    if normalized and normalized != search.strip().lower():
        pattern = f"%{normalized}%"
        conditions.extend(
            _normalized_column(column).like(pattern)
            for column in (NewsArticle.title, NewsArticle.excerpt, NewsArticle.content)
        )
    return or_(*conditions)


def _apply_news_filters(query, filters: NewsFiltersModel):
    """SQL-level filtering (spec F). Every filter narrows in the database, not
    in memory, so the feed scales with the corpus rather than the page size."""
    if filters.category:
        query = query.filter(NewsArticle.category == filters.category)
    if filters.publisher:
        query = query.filter(NewsArticle.publisher.ilike(f"%{filters.publisher}%"))
    if filters.symbol:
        # JSON array containment — checked case-insensitively by normalizing the
        # requested ticker, since the stored values are always upper-case.
        query = query.filter(NewsArticle.related_symbols.contains(filters.symbol.strip().upper()))
    if filters.event_type:
        query = query.filter(NewsArticle.event_type == filters.event_type.strip().upper())
    if filters.priority:
        query = query.filter(NewsArticle.priority == filters.priority.strip().upper())
    if filters.min_impact is not None:
        query = query.filter(NewsArticle.impact_score >= filters.min_impact)
    if filters.date_from:
        query = query.filter(NewsArticle.published_at >= filters.date_from)
    if filters.date_to:
        # `date_to` is a plain date; include the whole day rather than stopping
        # at midnight, which would silently hide the day the user asked for.
        query = query.filter(NewsArticle.published_at < filters.date_to + timedelta(days=1))
    return query


@app.post("/api/news/search")
async def search_news(filters: NewsFiltersModel):
    """Search and filter news articles with pagination.

    With a query and `sort=relevance`, ranking uses BM25 over headline+body with
    a headline field boost and fuzzy term expansion (see `news_analytics`), so
    results are ordered by how well they match rather than by whether a
    substring happens to appear. `sort=impact` ranks by the computed impact
    score instead, and `sort=recent` (the default) is plain recency.
    """
    try:
        with session_scope() as db:
            base = _apply_news_filters(db.query(NewsArticle), filters)
            total = base.count()

            relevance: dict[int, float] | None = None
            if filters.search:
                # Pre-filter with SQL ILIKE for recall, then re-rank the matched
                # set with BM25. ILIKE alone finds "bank"; BM25 figures out that
                # a headline match matters more than a passing mention.
                strict = base.filter(_news_text_condition(filters.search))
                total = strict.count()
                # A strict substring match returning nothing is the normal case
                # for a typo, an inflected form, or a hyphenation difference
                # ("kse-100" vs "kse100"). Rather than answering "0 results" for
                # a query the corpus can obviously satisfy, fall back to ranking
                # the recent corpus with BM25's fuzzy term expansion.
                exact_only = bool(total)
                pool = strict if exact_only else base
                candidates = pool.order_by(desc(NewsArticle.published_at)).limit(
                    int(settings.news_max_items_per_request) * 5
                ).all()
                index = news_analytics.BM25Index(
                    [(a.id, a.title or "", f"{a.excerpt or ''} {a.content or ''}") for a in candidates],
                    title_boost=settings.news_search_title_boost,
                )
                ranked = index.search(filters.search, top_n=len(candidates), fuzzy=settings.news_search_fuzzy)
                if not exact_only:
                    # No SQL substring match: the honest total is the number of
                    # genuine BM25 hits in the scanned window, not the window size.
                    total = len(ranked)
                    hit_ids = {doc_id for doc_id, _ in ranked}
                    candidates = [a for a in candidates if a.id in hit_ids]
                if filters.sort == "relevance" and not ranked:
                    candidates = []

                # Score every hit, whichever sort was asked for — the client
                # shows the same relevance number either way.
                relevance = {doc_id: round(score, 4) for doc_id, score in ranked}
                if filters.sort == "relevance":
                    ordered = sorted(
                        candidates,
                        key=lambda a: (-relevance.get(a.id, 0.0), -(a.impact_score or 0)),
                    )
                    offset = (filters.page - 1) * filters.page_size
                    articles = ordered[offset:offset + filters.page_size]
                else:
                    articles = _paginate_candidates(candidates, filters)
            else:
                articles = _paginate_candidates(base, filters, from_query=True)

            items = []
            for article in articles:
                item = _news_item(article)
                if filters.search:
                    item["relevance_score"] = (relevance or {}).get(article.id, 0.0)
                items.append(item)

            return {
                "items": items,
                "pagination": _news_pagination(filters.page, filters.page_size, total),
                "sort": filters.sort,
                "filters_applied": {
                    "category": filters.category,
                    "publisher": filters.publisher,
                    "symbol": filters.symbol,
                    "event_type": filters.event_type,
                    "priority": filters.priority,
                    "min_impact": filters.min_impact,
                    "date_from": str(filters.date_from) if filters.date_from else None,
                    "date_to": str(filters.date_to) if filters.date_to else None,
                    "search": filters.search,
                    "sort": filters.sort,
                },
            }
    except Exception as e:
        logger.error(f"News search failed: {e}")
        raise HTTPException(500, f"News search failed: {str(e)}")


def _order_news(query, sort: str):
    """SQL ordering for the non-relevance sorts. Impact sorts put the most
    consequential story first regardless of age; `priority` breaks ties then
    recency does."""
    if sort == "impact":
        return query.order_by(desc(NewsArticle.impact_score), desc(NewsArticle.published_at))
    return query.order_by(desc(NewsArticle.published_at))


def _published_key(article) -> float:
    """Sort key for publication time — naive datetimes are treated as UTC so a
    mixed corpus never raises "can't compare offset-naive and offset-aware"."""
    if article.published_at is None:
        return 0.0
    value = article.published_at
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


def _paginate_candidates(source, filters: NewsFiltersModel, *, from_query: bool = False):
    """Page either a SQLAlchemy query or an already-fetched candidate list."""
    offset = (filters.page - 1) * filters.page_size
    if from_query:
        return _order_news(source, filters.sort).offset(offset).limit(filters.page_size).all()
    if filters.sort == "impact":
        ordered = sorted(source, key=lambda a: (-_score_or_zero(a.impact_score), -_published_key(a)))
    else:
        ordered = sorted(source, key=lambda a: -_published_key(a))
    return ordered[offset:offset + filters.page_size]


def _score_or_zero(value) -> float:
    return float(value) if value is not None else 0.0

@app.get("/api/news/latest")
async def get_latest_news(limit: int = 20, category: Optional[str] = None,
                         symbol: Optional[str] = None, sort: str = "recent"):
    """Latest news articles (optionally one category or one ticker)."""
    try:
        with session_scope() as db:
            query = db.query(NewsArticle)
            if category:
                query = query.filter(NewsArticle.category == category)
            if symbol:
                query = query.filter(NewsArticle.related_symbols.contains(symbol.strip().upper()))

            articles = _order_news(query, sort).limit(min(limit, 100)).all()
            return {"items": [_news_item(a) for a in articles], "count": len(articles), "sort": sort}
    except Exception as e:
        logger.error(f"Failed to get latest news: {e}")
        raise HTTPException(500, f"Failed to get news: {str(e)}")

@app.get("/api/news/hero")
async def get_hero_news(hours: int = 72):
    """The lead story for the desk.

    Ranked by the computed impact score rather than "newest with a picture":
    the most consequential recent story is the right hero even when a routine
    wire item was published five minutes later. Preference is given to items
    that have both an image and an excerpt (they render properly), but the
    fallback chain ends at any recent article at all — a text-only hero beats
    an empty hero, and no article is ever invented to fill the slot.
    """
    try:
        with session_scope() as db:
            since = datetime.now(timezone.utc) - timedelta(hours=max(int(hours), 1))
            recent = db.query(NewsArticle).filter(NewsArticle.published_at >= since)

            article = recent.filter(and_(
                NewsArticle.image_url.isnot(None),
                NewsArticle.excerpt.isnot(None),
            )).order_by(
                desc(NewsArticle.impact_score), desc(NewsArticle.published_at)
            ).first()

            if not article:
                article = recent.order_by(
                    desc(NewsArticle.impact_score), desc(NewsArticle.published_at)
                ).first()

            if not article:
                # Nothing inside the window: fall back to the newest stored item
                # rather than claiming there is no news in an empty database.
                article = db.query(NewsArticle).order_by(
                    desc(NewsArticle.published_at)
                ).first()

            if not article:
                return {"hero": None, "reason": "No articles are stored yet — trigger /api/news/refresh to ingest real feeds."}

            return {"hero": _news_item(article)}
    except Exception as e:
        logger.error(f"Failed to get hero news: {e}")
        raise HTTPException(500, f"Failed to get hero news: {str(e)}")


@app.get("/api/news/by-symbol/{symbol}")
async def get_news_by_symbol(symbol: str, limit: int = 10, live: bool = True):
    """News related to one ticker (spec I).

    The stored corpus is searched first. If it holds nothing for this ticker,
    the route asks the publisher's own feed for that company directly and stores
    what comes back — so a stock page shows real coverage for all ~60 tickers
    the terminal knows, not just the handful that happened to appear in the
    general feed. `live=false` disables that fallback (pure database read).
    """
    try:
        symbol = (symbol or "").strip().upper()
        if not symbol:
            raise HTTPException(400, "A symbol is required")
        limit = max(1, min(limit, 50))
        news_service = get_news_service()
        used_live_fallback = False

        with session_scope() as db:
            articles = db.query(NewsArticle)\
                        .filter(NewsArticle.related_symbols.contains(symbol))\
                        .order_by(desc(NewsArticle.impact_score), desc(NewsArticle.published_at))\
                        .limit(limit)\
                        .all()

            if not articles and live:
                fetched = await news_service.fetch_symbol_news(symbol)
                if fetched:
                    corpus = news_service.corpus_for(db)
                    enriched = news_service.enrich_articles(fetched, corpus)
                    news_service.store_articles(db, enriched)
                    articles = db.query(NewsArticle)\
                                .filter(NewsArticle.related_symbols.contains(symbol))\
                                .order_by(desc(NewsArticle.impact_score), desc(NewsArticle.published_at))\
                                .limit(limit)\
                                .all()
                    used_live_fallback = True

            items = [_news_item(a) for a in articles]

        aggregate = {
            "count": len(items),
            "bullish": sum(1 for i in items if i["sentiment"]["label"] == "bullish"),
            "bearish": sum(1 for i in items if i["sentiment"]["label"] == "bearish"),
            "neutral": sum(1 for i in items if i["sentiment"]["label"] == "neutral"),
            "avg_impact": round(sum((i["impact_score"] or 0) for i in items) / len(items), 2) if items else None,
        }
        return {
            "symbol": symbol,
            "items": items,
            "count": len(items),
            "sentiment_aggregate": aggregate,
            "live_fallback_used": used_live_fallback,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get news for symbol {symbol}: {e}")
        raise HTTPException(500, f"Failed to get news: {str(e)}")

@app.get("/api/news/categories")
async def get_news_categories():
    """Get available news categories with article counts."""
    try:
        with session_scope() as db:
            # Get category counts
            categories = db.query(
                NewsArticle.category,
                func.count(NewsArticle.id).label('count')
            ).group_by(NewsArticle.category)\
             .order_by(desc('count'))\
             .all()
            
            return {
                "categories": [
                    {"name": cat, "count": count}
                    for cat, count in categories
                ]
            }
    except Exception as e:
        logger.error(f"Failed to get categories: {e}")
        raise HTTPException(500, f"Failed to get categories: {str(e)}")

@app.get("/api/news/publishers")
async def get_news_publishers():
    """Get available news publishers."""
    try:
        with session_scope() as db:
            publishers = db.query(NewsArticle.publisher)\
                          .filter(NewsArticle.publisher.isnot(None))\
                          .distinct()\
                          .order_by(NewsArticle.publisher)\
                          .all()
            
            return {
                "publishers": [p[0] for p in publishers if p[0]]
            }
    except Exception as e:
        logger.error(f"Failed to get publishers: {e}")
        raise HTTPException(500, f"Failed to get publishers: {str(e)}")

@app.get("/api/news/image")
async def proxy_news_image(url: str):
    """Re-serve one publisher image from an allow-listed host.

    A retry path, not the primary one: the frontend loads images straight from
    the publisher and only falls back to this when the browser request is
    blocked (several publisher CDNs answer cross-origin `<img>` requests with
    403 while serving a server request normally).

    Safety is by construction — https only, hostname must match a fixed
    allowlist, no credentials and no custom port, an image content-type is
    required, and the body is size-capped before it is returned. A URL that is
    not allow-listed is rejected before any outbound request happens.
    """
    try:
        content_type, body = await get_news_service().fetch_image(url)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        logger.warning("news image proxy failed for %s: %s", url, exc)
        raise HTTPException(502, f"Could not fetch that image: {exc}")
    return Response(
        content=body,
        media_type=content_type,
        headers={
            # Publisher images are immutable in practice; cache hard so a retry
            # is a one-off cost rather than a per-render one.
            "Cache-Control": "public, max-age=86400, immutable",
        },
    )


@app.get("/api/news/sources")
async def get_news_sources():
    """Real health of every configured news feed (spec: source integrity).

    Reports the last observed HTTP status, item count and error for each feed —
    including the ones deliberately switched off — so the desk can show which
    publishers are actually contributing right now instead of implying full
    coverage it does not have.
    """
    try:
        news_service = get_news_service()
        statuses = news_service.source_status()
        registry = [{
            "key": f.key, "name": f.name, "region": f.region, "url": f.url,
            "category": f.category, "source_type": f.source_type,
            "enabled": f.enabled, "note": f.note,
        } for f in NEWS_FEEDS]
        healthy = sum(1 for s in statuses if s.get("status") == "OK")
        return {
            "sources": statuses,
            "registry": registry,
            "summary": {
                "total_feeds": len(NEWS_FEEDS),
                "enabled_feeds": len(news_enabled_feeds()),
                "healthy_feeds": healthy,
                "items_available": sum(int(s.get("items") or 0) for s in statuses),
                "last_ingest_at": news_service.last_ingest_at.isoformat() if news_service.last_ingest_at else None,
                "paid_sources_configured": [
                    name for name, configured in (
                        ("newsapi", bool(settings.newsapi_key)),
                        ("finnhub", bool(settings.finnhub_api_key)),
                        ("alpha_vantage", bool(settings.alpha_vantage_key)),
                    ) if configured
                ],
            },
        }
    except Exception as e:
        logger.error(f"Failed to get news sources: {e}")
        raise HTTPException(500, f"Failed to get news sources: {str(e)}")


@app.get("/api/news/stats")
async def get_news_stats(hours: int = 168):
    """Desk statistics computed from the stored corpus — no estimated numbers."""
    try:
        since = datetime.now(timezone.utc) - timedelta(hours=max(int(hours), 1))
        with session_scope() as db:
            window = db.query(NewsArticle).filter(NewsArticle.published_at >= since)
            total = db.query(func.count(NewsArticle.id)).scalar() or 0
            in_window = window.count()

            by_category = dict(
                db.query(NewsArticle.category, func.count(NewsArticle.id))
                  .filter(NewsArticle.published_at >= since)
                  .group_by(NewsArticle.category).all()
            )
            by_event = dict(
                db.query(NewsArticle.event_type, func.count(NewsArticle.id))
                  .filter(NewsArticle.published_at >= since)
                  .group_by(NewsArticle.event_type).all()
            )
            by_priority = dict(
                db.query(NewsArticle.priority, func.count(NewsArticle.id))
                  .filter(NewsArticle.published_at >= since)
                  .group_by(NewsArticle.priority).all()
            )
            by_mode = dict(
                db.query(NewsArticle.data_mode, func.count(NewsArticle.id))
                  .filter(NewsArticle.published_at >= since)
                  .group_by(NewsArticle.data_mode).all()
            )
            publishers = db.query(func.count(func.distinct(NewsArticle.publisher))).scalar() or 0
            with_symbols = window.filter(NewsArticle.related_symbols != "[]").count()
            avg_impact = db.query(func.avg(NewsArticle.impact_score))\
                           .filter(NewsArticle.published_at >= since).scalar()
            newest = db.query(func.max(NewsArticle.published_at)).scalar()

            return {
                "window_hours": hours,
                "total_articles": int(total),
                "articles_in_window": in_window,
                "publishers": int(publishers),
                "articles_with_symbols": with_symbols,
                "avg_impact_score": round(float(avg_impact), 2) if avg_impact is not None else None,
                "newest_published_at": newest.isoformat() if newest else None,
                "by_category": by_category,
                "by_event_type": by_event,
                "by_priority": by_priority,
                "by_data_mode": by_mode,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
    except Exception as e:
        logger.error(f"Failed to compute news stats: {e}")
        raise HTTPException(500, f"Failed to compute news stats: {str(e)}")


@app.get("/api/news/trending")
async def get_trending_news(window_hours: int = 72, top: int = 12):
    """What the market is being talked about most right now.

    Time-decayed mention counts (see `news_analytics.trending_entities`) over
    validated symbols, indices and topics — the ranking reflects attention in
    the window, not raw volume since the beginning of time.
    """
    try:
        window_hours = max(int(window_hours), 1)
        top = max(1, min(int(top), 50))
        since = datetime.now(timezone.utc) - timedelta(hours=window_hours)
        with session_scope() as db:
            rows = db.query(NewsArticle).filter(NewsArticle.published_at >= since)\
                     .order_by(desc(NewsArticle.published_at)).limit(2000).all()
            articles = [{
                "published_at": r.published_at,
                "related_symbols": r.related_symbols or [],
                "related_indices": r.related_indices or [],
                "topics": getattr(r, "topics", None) or [],
                "sentiment_score": r.sentiment_score,
                "impact_score": r.impact_score,
            } for r in rows]

        trending = news_analytics.trending_entities(
            articles, window_hours=window_hours, top_n=top,
            half_life_hours=max(window_hours / 3.0, 1.0),
        )
        trending["articles_considered"] = len(articles)
        return trending
    except Exception as e:
        logger.error(f"Failed to compute trending news: {e}")
        raise HTTPException(500, f"Failed to compute trending news: {str(e)}")


class NewsClusterRequest(BaseModel):
    """Parameters for story clustering.

    The default cosine threshold of 0.30 was chosen against a live corpus of
    real PSX/global feeds: 0.22 merged unrelated syndicated columns (every
    "stocks making the biggest moves" round-up landed in one cluster), while
    0.45 split genuinely-same stories. 0.30 keeps the real multi-outlet story
    (the SBP policy-rate decision grouping ~10 outlets) intact.
    """
    window_hours: int = Field(72, ge=1, le=720)
    category: Optional[str] = None
    symbol: Optional[str] = None
    threshold: float = Field(0.30, ge=0.05, le=0.9)
    limit: int = Field(400, ge=10, le=2000)


@app.post("/api/news/clusters")
async def get_news_clusters(request: NewsClusterRequest):
    """Group articles covering the same underlying story.

    This is what turns a flat feed into "four outlets are reporting this" — a
    real signal about how important a story is, computed with TF-IDF cosine
    similarity rather than by matching titles.
    """
    try:
        since = datetime.now(timezone.utc) - timedelta(hours=request.window_hours)
        with session_scope() as db:
            query = db.query(NewsArticle).filter(NewsArticle.published_at >= since)
            if request.category:
                query = query.filter(NewsArticle.category == request.category)
            if request.symbol:
                query = query.filter(NewsArticle.related_symbols.contains(request.symbol.strip().upper()))
            rows = _order_news(query, "recent").limit(request.limit).all()

            articles = [{
                "id": r.id,
                "title": r.title or "",
                "excerpt": r.excerpt or "",
                "content": r.content or "",
                "publisher": r.publisher,
                "published_at": r.published_at,
                "related_symbols": r.related_symbols or [],
                "event_type": getattr(r, "event_type", None),
                "impact_score": r.impact_score,
            } for r in rows]

        clusters = news_analytics.cluster_articles(articles, threshold=request.threshold)
        multi_source = [c for c in clusters if c.size > 1]
        return {
            "clusters": [c.as_dict() for c in clusters],
            "count": len(clusters),
            "multi_source_count": len(multi_source),
            "articles_analyzed": len(articles),
            "threshold": request.threshold,
            "disclaimer": "Story grouping is a lexical similarity heuristic over fetched headline/lede text, not an editorial judgement.",
        }
    except Exception as e:
        logger.error(f"Failed to cluster news: {e}")
        raise HTTPException(500, f"Failed to cluster news: {str(e)}")


@app.get("/api/news/{article_id}/related")
async def get_related_news(article_id: int, limit: int = 6):
    """Articles related to one article.

    Relatedness is a combination of shared validated entities (the strongest
    signal — the same ticker or index), the same event type, and BM25 text
    similarity against the article's own headline and lede.
    """
    try:
        limit = max(1, min(limit, 25))
        with session_scope() as db:
            article = db.query(NewsArticle).filter(NewsArticle.id == article_id).first()
            if not article:
                raise HTTPException(404, "Article not found")

            since = (article.published_at - timedelta(days=30)) if article.published_at else None
            query = db.query(NewsArticle).filter(NewsArticle.id != article.id)
            if since is not None:
                query = query.filter(NewsArticle.published_at >= since)

            # Narrow to the candidate pool by any shared attribute the article
            # actually has, then rank within it. Falling back to "recent" keeps
            # the endpoint useful for a story with no entities at all.
            symbols = [s for s in (article.related_symbols or [])]
            narrowed = None
            for symbol in symbols:
                narrowed = query.filter(NewsArticle.related_symbols.contains(symbol))
                break
            if narrowed is None and article.category:
                narrowed = query.filter(NewsArticle.category == article.category)
            candidates = (narrowed or query).order_by(desc(NewsArticle.published_at)).limit(300).all()

            index = news_analytics.BM25Index(
                [(c.id, c.title or "", f"{c.excerpt or ''} {c.content or ''}") for c in candidates],
                title_boost=settings.news_search_title_boost,
            )
            text_scores = dict(index.search(article.title or "", top_n=len(candidates),
                                            fuzzy=settings.news_search_fuzzy))
            entity_set = set(symbols) | set(article.related_indices or [])

            def relatedness(candidate) -> float:
                score = 0.0
                shared = entity_set & (set(candidate.related_symbols or []) | set(candidate.related_indices or []))
                score += 3.0 * len(shared)
                if getattr(candidate, "event_type", None) and candidate.event_type == article.event_type:
                    score += 1.0
                score += text_scores.get(candidate.id, 0.0)
                return score

            ranked = sorted(candidates, key=lambda c: (-relatedness(c), -_published_key(c)))[:limit]
            return {
                "article_id": article_id,
                "items": [_news_item(c) for c in ranked],
                "count": len(ranked),
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get related news for {article_id}: {e}")
        raise HTTPException(500, f"Failed to get related news: {str(e)}")


@app.get("/api/news/{article_id}")
async def get_news_article(article_id: int):
    """Get full news article by ID."""
    try:
        with session_scope() as db:
            article = db.query(NewsArticle).filter(NewsArticle.id == article_id).first()
            
            if not article:
                raise HTTPException(404, "Article not found")
            
            return _news_item(article, full=True)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get article {article_id}: {e}")
        raise HTTPException(500, f"Failed to get article: {str(e)}")

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
