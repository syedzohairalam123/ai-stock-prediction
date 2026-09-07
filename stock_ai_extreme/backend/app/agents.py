from __future__ import annotations
from datetime import date,timedelta
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error,mean_squared_error,r2_score
from sklearn.model_selection import TimeSeriesSplit
from .conformal import calibrate_split_conformal
from .indicators import add_indicators
from .providers import MarketDataManager, ProviderError

class DataAgent:
    """Phase 2: no longer talks to yfinance directly — everything goes through
    a MarketDataManager, which adds caching, retries, and provider fallback."""
    def __init__(self, manager: MarketDataManager):
        self.manager = manager

    async def history(self, ticker: str, start: date, end: date, interval: str = "1d"):
        """Returns (enriched_dataframe, source_name, status) instead of a bare frame,
        so callers can show the user exactly where the data came from and how fresh it is."""
        try:
            frame, source, status = await self.manager.history(ticker, start, end, interval)
        except ProviderError as exc:
            raise ValueError(str(exc)) from exc
        cleaned = frame[[c for c in ["Open", "High", "Low", "Close", "Volume"] if c in frame]].dropna()
        if cleaned.empty:
            raise ValueError("No usable rows after cleaning. Verify ticker and date range.")
        return add_indicators(cleaned), source, status

    async def profile(self, ticker: str) -> dict:
        try:
            return await self.manager.profile(ticker)
        except ProviderError as exc:
            raise ValueError(str(exc)) from exc

class PredictionAgent:
    # Phase 7: widened past the original OHLCV+basic-TA set to also use the
    # Phase 5 indicators (ATR/Stochastic/ADX/VWAP) as model features.
    cols=["Open","High","Low","Close","Volume","sma_10","sma_30","ema_10","ema_26","rsi_14","macd","macd_signal",
          "bb_upper","bb_lower","atr_14","stoch_k","stoch_d","adx_14","vwap_14"]
    def tabular(self,df,horizon,kind="rf"):
        cols=[c for c in self.cols if c in df.columns]  # older callers / shorter frames may lack some Phase 5 cols
        z=df.copy(); z["target"]=z.Close.shift(-1); z=z.dropna(subset=cols+["target"])
        if len(z)<100: raise ValueError("Use a longer range: 100 usable trading rows are required.")
        X,y=z[cols],z.target
        factory=(lambda:Ridge(alpha=1.0)) if kind=="ridge" else (lambda:RandomForestRegressor(n_estimators=300,min_samples_leaf=2,n_jobs=-1,random_state=42))
        vals=[]
        for tr,te in TimeSeriesSplit(n_splits=4).split(X):
            m=factory();m.fit(X.iloc[tr],y.iloc[tr]);p=m.predict(X.iloc[te]); vals.append((mean_absolute_error(y.iloc[te],p),mean_squared_error(y.iloc[te],p)**.5))
        m=factory();m.fit(X,y); mae,rmse=map(float,np.mean(vals,axis=0))

        # Phase 8: split-conformal interval instead of assuming Gaussian errors.
        # Falls back to the RMSE band only if there's not enough data to calibrate on.
        try: conformal=calibrate_split_conformal(factory,X,y,confidence=0.9)
        except ValueError: conformal=None

        row=z.iloc[-1].copy(); out=[]
        for _ in range(horizon):
            v=float(m.predict(row[cols].astype(float).to_frame().T)[0]);out.append(v); row["Open"]=row["Close"];row["Close"]=v;row["High"]=max(float(row.High),v);row["Low"]=min(float(row.Low),v);row["sma_10"]=(float(row.sma_10)*9+v)/10;row["sma_30"]=(float(row.sma_30)*29+v)/30;row["ema_10"]=v*2/11+float(row.ema_10)*9/11;row["ema_26"]=v*2/27+float(row.ema_26)*25/27;row["macd"]=row.ema_10-row.ema_26;row["macd_signal"]=.2*row.macd+.8*row.macd_signal
        return self._pack(df,out,rmse,conformal),{"mae":round(mae,4),"rmse":round(rmse,4),"r2_train":round(float(r2_score(y,m.predict(X))),4),"model":kind,
                "interval_method":"conformal_90pct" if conformal else "gaussian_rmse"}
    def _pack(self,df,preds,rmse,conformal=None):
        cur=pd.Timestamp(df.index[-1]).date(); dates=[]
        while len(dates)<len(preds):
            cur+=timedelta(days=1)
            if cur.weekday()<5: dates.append(cur)
        out=[]
        for i,(d,p) in enumerate(zip(dates,preds)):
            hw=conformal.half_width_for_step(i+1) if conformal else 1.96*rmse
            out.append({"date":d.isoformat(),"price":round(float(p),4),"lower":round(float(p-hw),4),"upper":round(float(p+hw),4)})
        return out

class InsightAgent:
    def make(self,df,preds,metrics):
        last=float(df.Close.iloc[-1]); final=float(preds[-1]["price"]); change=(final-last)/last*100; rsi=float(df.rsi_14.iloc[-1]); vol=float(df.returns.tail(30).std())
        trend="bullish" if change>1 else "bearish" if change<-1 else "sideways"; risk="HIGH" if vol>.03 or metrics["rmse"]>last*.04 else "MEDIUM" if vol>.015 else "LOW"
        return {"risk_level":risk,"insights":[f"Forecast trend: {trend}; estimated horizon change: {change:.2f}%.",f"RSI: {rsi:.1f}; "+("overbought pressure may be present." if rsi>70 else "oversold pressure may be present." if rsi<30 else "momentum is within a neutral range."),f"30-day return volatility: {vol*100:.2f}%; validation RMSE: {metrics['rmse']:.2f}.","This output is educational analytics, not investment advice or a guarantee."]}
