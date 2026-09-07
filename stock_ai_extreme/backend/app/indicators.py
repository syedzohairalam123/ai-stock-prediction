import numpy as np
import pandas as pd

def _wilder(series: pd.Series, period: int) -> pd.Series:
    """Wilder's smoothing (used by ATR/ADX) — equivalent to an EWM with alpha=1/period."""
    return series.ewm(alpha=1 / period, adjust=False).mean()

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    x=df.copy(); c=x["Close"]; h=x.get("High"); l=x.get("Low"); v=x.get("Volume")
    x["sma_10"]=c.rolling(10).mean(); x["sma_30"]=c.rolling(30).mean()
    x["ema_10"]=c.ewm(span=10,adjust=False).mean(); x["ema_26"]=c.ewm(span=26,adjust=False).mean()
    d=c.diff(); gain=d.clip(lower=0).rolling(14).mean(); loss=(-d.clip(upper=0)).rolling(14).mean()
    rs=gain/loss.replace(0,np.nan); rsi=100-(100/(1+rs))
    rsi=rsi.where(loss!=0,100.0)              # zero loss (no down-days at all) -> max RSI=100, not NaN
    rsi=rsi.where(~((gain==0)&(loss==0)),50.0) # zero movement whatsoever -> neutral 50
    x["rsi_14"]=rsi
    x["macd"]=x["ema_10"]-x["ema_26"]; x["macd_signal"]=x["macd"].ewm(span=9,adjust=False).mean()
    mid=c.rolling(20).mean(); sd=c.rolling(20).std(); x["bb_upper"]=mid+2*sd; x["bb_lower"]=mid-2*sd
    x["returns"]=c.pct_change()

    if h is not None and l is not None:
        prev_close=c.shift(1)
        tr=pd.concat([h-l,(h-prev_close).abs(),(l-prev_close).abs()],axis=1).max(axis=1)
        x["atr_14"]=_wilder(tr,14)

        # Stochastic Oscillator: %K compares today's close to the recent trading range, %D smooths it.
        lowest_low=l.rolling(14).min(); highest_high=h.rolling(14).max()
        x["stoch_k"]=100*(c-lowest_low)/(highest_high-lowest_low).replace(0,np.nan)
        x["stoch_d"]=x["stoch_k"].rolling(3).mean()

        # ADX: trend-strength indicator built from smoothed +DI/-DI directional movement.
        up_move=h.diff(); down_move=-l.diff()
        plus_dm=np.where((up_move>down_move)&(up_move>0),up_move,0.0)
        minus_dm=np.where((down_move>up_move)&(down_move>0),down_move,0.0)
        atr_for_di=_wilder(tr,14).replace(0,np.nan)
        plus_di=100*_wilder(pd.Series(plus_dm,index=x.index),14)/atr_for_di
        minus_di=100*_wilder(pd.Series(minus_dm,index=x.index),14)/atr_for_di
        dx=100*(plus_di-minus_di).abs()/(plus_di+minus_di).replace(0,np.nan)
        x["adx_14"]=_wilder(dx,14); x["plus_di_14"]=plus_di; x["minus_di_14"]=minus_di

    if v is not None:
        # Rolling VWAP approximation — true intraday VWAP needs tick data we don't have on
        # daily bars, so this is a 14-day rolling volume-weighted average of the typical price.
        typical=(h+l+c)/3 if (h is not None and l is not None) else c
        pv=typical*v
        x["vwap_14"]=pv.rolling(14).sum()/v.rolling(14).sum().replace(0,np.nan)

    return x.dropna().copy()

