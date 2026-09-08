import { useEffect, useRef, useState } from 'react';
import { useSettingsStore } from '../store/useStore';

const WS_URL = import.meta.env.VITE_WS_URL || 'ws://127.0.0.1:8000';

export type LiveQuote = {
  type: string;
  ticker?: string;
  price?: number | null;
  source?: string;
  status?: string;
  timestamp?: string;
  message?: string;
};

export function useRealTimeStock(ticker: string, enabled: boolean = true) {
  const [quote, setQuote] = useState<LiveQuote | null>(null);
  const [state, setState] = useState<'connecting' | 'connected' | 'error' | 'reconnecting'>('connecting');
  const retryRef = useRef<number>();
  const socketRef = useRef<WebSocket | null>(null);
  const { autoRefresh, refreshInterval } = useSettingsStore();

  useEffect(() => {
    if (!enabled || !ticker) {
      setState('connecting');
      return;
    }

    let stopped = false;
    let socket: WebSocket;

    const connect = () => {
      if (stopped) return;

      setState('connecting');
      try {
        socket = new WebSocket(`${WS_URL}/ws/stock/${encodeURIComponent(ticker)}`);
        socketRef.current = socket;

        socket.onopen = () => {
          if (!stopped) {
            setState('connected');
          }
        };

        socket.onmessage = (event) => {
          if (!stopped) {
            try {
              const data = JSON.parse(event.data);
              setQuote(data);
            } catch (error) {
              console.error('Failed to parse WebSocket message:', error);
            }
          }
        };

        socket.onerror = (error) => {
          console.error('WebSocket error:', error);
          if (!stopped) {
            setState('error');
          }
        };

        socket.onclose = () => {
          if (!stopped && autoRefresh) {
            setState('reconnecting');
            retryRef.current = window.setTimeout(connect, refreshInterval);
          }
        };
      } catch (error) {
        console.error('Failed to create WebSocket connection:', error);
        if (!stopped) {
          setState('error');
        }
      }
    };

    connect();

    return () => {
      stopped = true;
      if (retryRef.current) {
        clearTimeout(retryRef.current);
      }
      if (socketRef.current) {
        socketRef.current.close();
      }
    };
  }, [ticker, enabled, autoRefresh, refreshInterval]);

  return { quote, state };
}