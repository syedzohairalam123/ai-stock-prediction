"""Optional TensorFlow LSTM forecaster. Install tensorflow from requirements first."""
from .recurrent_models import forecast_recurrent

class LSTMPredictionAgent:
    def predict(self,df,horizon=7,lookback=30,epochs=25):
        return forecast_recurrent(df,horizon,lookback,epochs,cell_type="lstm")

