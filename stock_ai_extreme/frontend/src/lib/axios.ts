import axios, { AxiosError, AxiosInstance } from 'axios';

const configuredApiUrl = (import.meta.env.VITE_API_URL || '/api').replace(/\/+$/, '');
const API_URL = /\/api$/i.test(configuredApiUrl) ? configuredApiUrl : `${configuredApiUrl}/api`;

// Create axios instance with base configuration
export const apiClient: AxiosInstance = axios.create({
  baseURL: API_URL,
  timeout: 30000, // 30 seconds timeout
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor for logging and auth
apiClient.interceptors.request.use(
  (config) => {
    if (config.url && /^\/api(?:\/|$)/i.test(config.url) && typeof config.baseURL === 'string' && /\/api$/i.test(config.baseURL)) {
      config.url = config.url.slice(4) || '/';
    }
    // Add any auth tokens here if needed
    // Silent operation - no console logging
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Response interceptor for error handling
apiClient.interceptors.response.use(
  (response) => {
    return response;
  },
  (error: AxiosError) => {
    const errorData = error.response?.data as any;
    const detail = errorData?.detail;

    // Silent error handling - don't log to console to avoid spam
    // The service layer will handle fallbacks gracefully

    // Handle specific error cases
    if (error.code === 'ECONNABORTED') {
      return Promise.reject(new Error('Request timeout. Please try again.'));
    }

    if (!error.response) {
      return Promise.reject(new Error('Network error. Please check your connection.'));
    }

    // Some endpoints (the Phase 20 paper-trading API) return a structured
    // detail object `{ message, issues, ... }` so a caller can highlight the
    // exact invalid field. Keep that structure on the rejected error instead of
    // stringifying it to "[object Object]" — plain string details behave
    // exactly as they always did.
    let errorMessage: string;
    if (typeof detail === 'string') {
      errorMessage = detail;
    } else if (Array.isArray(detail)) {
      // FastAPI/Pydantic request-validation errors
      const first = detail[0] as { msg?: string } | undefined;
      errorMessage = first?.msg || error.message || 'An error occurred';
    } else if (detail && typeof detail === 'object' && typeof (detail as any).message === 'string') {
      errorMessage = (detail as any).message;
    } else {
      errorMessage = error.message || 'An error occurred';
    }

    const wrapped = new Error(errorMessage) as Error & {
      detail?: unknown;
      issues?: unknown;
      status?: number;
    };
    if (detail !== undefined) wrapped.detail = detail;
    if (detail && typeof detail === 'object' && !Array.isArray(detail) && (detail as any).issues) {
      wrapped.issues = (detail as any).issues;
    }
    wrapped.status = error.response?.status;

    return Promise.reject(wrapped);
  }
);

export default apiClient;