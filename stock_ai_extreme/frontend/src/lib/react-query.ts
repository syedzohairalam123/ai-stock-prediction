import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ReactQueryDevtools } from '@tanstack/react-query-devtools';
import { ReactNode } from 'react';
import React from 'react';

// Create a client
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Refetch data every 30 seconds by default
      refetchInterval: 30000,
      // Keep data fresh for 5 minutes
      staleTime: 5 * 60 * 1000,
      // Retry failed requests 3 times
      retry: 3,
      // Retry with exponential backoff
      retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 30000),
      // Cache time
      gcTime: 10 * 60 * 1000,
      // Disable React Query DevTools profiling to avoid errors
      refetchOnWindowFocus: false,
    },
    mutations: {
      retry: 1,
    },
  },
});

interface QueryProviderProps {
  children: ReactNode;
}

export function QueryProvider({ children }: QueryProviderProps) {
  const devTools = import.meta.env.DEV ? React.createElement(ReactQueryDevtools, { 
    initialIsOpen: false,
  }) : null;
  return React.createElement(QueryClientProvider, { client: queryClient }, children, devTools);
}