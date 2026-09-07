from contextlib import asynccontextmanager
from datetime import date
import asyncio
import logging
import math
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
from .db import init_db
from . import repository as repo
from .providers import MarketDataManager,YFinanceProvider,FinnhubProvider

logger=logging.getLogger("neural_market.main")

@asynccontextmanager
async def lifespan(app:FastAPI):
    init_db()  # Phase 3: create tables on startup if they don't already exist
    yield

app=FastAPI(title="Neural Market API",version="2.2.0",description="Stock analytics and educational ML forecasting API",lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=[v.strip() for v in settings.cors_origins.split(',')],allow_credentials=True,allow_methods=["*"],allow_headers=["*"])

# Phase 2: provider manager. yfinance is primary; Finnhub is an optional live-quote
# fallback that only activates if FINNHUB_API_KEY is set (skipped otherwise — no
# API key is required to run the app). Add a new provider here, nowhere else,
# when onboarding another data source later.
manager=MarketDataManager(
    providers=[YFinanceProvider(max_retries=settings.provider_max_retries),FinnhubProvider(settings.finnhub_api_key)],
    history_cache_ttl=settings.history_cache_ttl_seconds,
    quote_cache_ttl=settings.quote_cache_ttl_seconds,
    profile_cache_ttl=settings.profile_cache_ttl_seconds,
)
data,predictor,insighter,lstm,gru=DataAgent(manager),PredictionAgent(),InsightAgent(),LSTMPredictionAgent(),GRUPredictionAgent()

class HistoryRequest(BaseModel): start:date; end:date; interval:str="1d"
class PredictRequest(HistoryRequest): horizon:int=Field(7,ge=1,le=30); model:str="rf"; lstm_epochs:int=Field(25,ge=5,le=100)
class BacktestRequest(BaseModel): start:date; end:date; model:str="ridge"; test_days:int=Field(60,ge=10,le=250); refit_every:int=Field(5,ge=1,le=30)
class WatchlistAddRequest(BaseModel): ticker:str; note:Optional[str]=None

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
        return await data.profile(ticker)
    except Exception as e: raise HTTPException(400,str(e))

@app.post("/api/stocks/{ticker}/history")
async def history(ticker:str,body:HistoryRequest):
 try:
  d,source,status=await data.history(ticker,body.start,body.end,body.interval)
  out=d.reset_index().rename(columns={d.index.name or "index":"date"});out.date=out.date.astype(str)
  return {"rows":out.where(out.notna(),None).to_dict("records"),"meta":{"source":source,"status":status.value}}
 except Exception as e: raise HTTPException(400,str(e))

@app.post("/api/stocks/{ticker}/predict")
async def forecast(ticker:str,body:PredictRequest):
 try:
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

@app.websocket("/ws/stock/{ticker}")
async def stream(websocket:WebSocket,ticker:str):
 await websocket.accept()
 try:
  while True:
   try:
    q=await manager.quote(ticker)
    price=None if math.isnan(q.price) else round(q.price,4)
    await websocket.send_json({"type":"price","ticker":q.ticker,"price":price,"source":q.source,"status":q.status.value,"timestamp":q.timestamp.isoformat()})
   except Exception as e: await websocket.send_json({"type":"error","message":str(e)})
   await asyncio.sleep(settings.live_poll_seconds)
 except WebSocketDisconnect: pass
