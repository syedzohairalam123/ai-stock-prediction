from contextlib import asynccontextmanager
from datetime import date,timedelta
import asyncio
import logging
import math
import pandas as pd
from fastapi import FastAPI,HTTPException,WebSocket,WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel,Field
from typing import Optional
from .config import settings
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
from .providers import MarketDataManager,YFinanceProvider,FinnhubProvider,DataStatus

logger=logging.getLogger("neural_market.main")

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
