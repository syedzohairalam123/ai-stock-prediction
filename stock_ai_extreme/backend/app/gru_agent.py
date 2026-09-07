"""Optional TensorFlow GRU forecaster — a lighter-weight recurrent alternative
to LSTM (fewer gates/parameters, usually faster to train, often comparable
accuracy on shorter sequences). Install tensorflow from requirements first."""
from .recurrent_models import forecast_recurrent

class GRUPredictionAgent:
    def predict(self,df,horizon=7,lookback=30,epochs=25):
        return forecast_recurrent(df,horizon,lookback,epochs,cell_type="gru")
