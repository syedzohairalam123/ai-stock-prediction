import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { addDays, subDays } from 'date-fns';
import apiClient from '../lib/axios';
import { format } from 'date-fns';

// Types
export interface StockHistory {
  date: string;
  Open: number;
  High: number;
  Low: number;
  Close: number;
  Volume: number;
  sma_10?: number;
  sma_30?: number;
  ema_10?: number;
  ema_26?: number;
  rsi_14?: number;
  macd?: number;
  macd_signal?: number;
  bb_upper?: number;
  bb_lower?: number;
  atr_14?: number;
  stoch_k?: number;
  stoch_d?: number;
  adx_14?: number;
  vwap_14?: number;
}

export interface StockProfile {
  ticker: string;
  name?: string;
  sector?: string;
  industry?: string;
  country?: string;
  website?: string;
  summary?: string;
  currency?: string;
  market_cap?: number;
  exchange?: string;
}

export interface Prediction {
  date: string;
  price: number;
  lower: number;
  upper: number;
}

export interface PredictionResponse {
  ticker: string;
  predictions: Prediction[];
  model_metrics: {
    mae: number;
    rmse: number;
    r2_train: number;
    model: string;
    interval_method: string;
  };
  insights: {
    risk_level: string;
    insights: string[];
  };
  baseline_comparison: {
    naive_persistence: {
      mae: number;
    };
  };
  beats_naive_baseline: boolean;
  data_meta: {
    source: string;
    status: string;
  };
  disclaimer: string;
}

export interface Quote {
  type: string;
  ticker?: string;
  price?: number | null;
  source?: string;
  status?: string;
  timestamp?: string;
  message?: string;
}

// API Functions
const getStockHistory = async (ticker: string, startDate: string, endDate: string) => {
  const response = await apiClient.post(`/api/stocks/${ticker}/history`, {
    start: startDate,
    end: endDate,
    interval: '1d',
  });
  return response.data;
};

const getStockProfile = async (ticker: string) => {
  const response = await apiClient.get(`/api/stocks/${ticker}/profile`);
  return response.data;
};

const getPrediction = async (
  ticker: string,
  startDate: string,
  endDate: string,
  model: string = 'rf',
  horizon: number = 7
) => {
  const response = await apiClient.post(`/api/stocks/${ticker}/predict`, {
    start: startDate,
    end: endDate,
    horizon,
    model,
    lstm_epochs: 20,
  });
  return response.data;
};

// React Query Hooks
export function useStockHistory(ticker: string, days: number = 730) {
  const endDate = new Date();
  const startDate = subDays(endDate, days);

  return useQuery({
    queryKey: ['stockHistory', ticker, format(startDate, 'yyyy-MM-dd'), format(endDate, 'yyyy-MM-dd')],
    queryFn: () => getStockHistory(ticker, format(startDate, 'yyyy-MM-dd'), format(endDate, 'yyyy-MM-dd')),
    enabled: !!ticker,
    refetchInterval: 60000, // Refetch every minute
  });
}

export function useStockProfile(ticker: string) {
  return useQuery({
    queryKey: ['stockProfile', ticker],
    queryFn: () => getStockProfile(ticker),
    enabled: !!ticker,
    refetchInterval: 3600000, // Refetch every hour
  });
}

export function usePrediction(ticker: string, model: string = 'rf', horizon: number = 7) {
  const endDate = new Date();
  const startDate = subDays(endDate, 730);

  return useQuery({
    queryKey: ['prediction', ticker, model, horizon],
    queryFn: () => getPrediction(ticker, format(startDate, 'yyyy-MM-dd'), format(endDate, 'yyyy-MM-dd'), model, horizon),
    enabled: !!ticker,
    refetchInterval: 300000, // Refetch every 5 minutes
  });
}

export function useCombinedStockData(ticker: string, model: string = 'rf') {
  const historyQuery = useStockHistory(ticker);
  const profileQuery = useStockProfile(ticker);
  const predictionQuery = usePrediction(ticker, model);

  return {
    history: historyQuery.data,
    profile: profileQuery.data,
    prediction: predictionQuery.data,
    isLoading: historyQuery.isLoading || profileQuery.isLoading || predictionQuery.isLoading,
    isError: historyQuery.isError || profileQuery.isError || predictionQuery.isError,
    error: historyQuery.error || profileQuery.error || predictionQuery.error,
    refetch: () => {
      historyQuery.refetch();
      profileQuery.refetch();
      predictionQuery.refetch();
    },
  };
}