import React, { Component, ErrorInfo, ReactNode } from 'react';
import { FallbackProps } from 'react-error-boundary';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
  errorInfo: ErrorInfo | null;
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
    errorInfo: null,
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error, errorInfo: null };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('Error caught by boundary:', error, errorInfo);
    this.setState({
      error,
      errorInfo,
    });
  }

  public render() {
    if (this.state.hasError) {
      return (
        <div className="error-boundary">
          <div className="error-content">
            <h2>Something went wrong</h2>
            <details className="error-details">
              <summary>Error details</summary>
              <pre>{this.state.error?.toString()}</pre>
              {this.state.errorInfo && (
                <pre>{this.state.errorInfo.componentStack}</pre>
              )}
            </details>
            <button
              onClick={() => window.location.reload()}
              className="error-retry-button"
            >
              Reload Page
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

// Fallback component for react-error-boundary
export function ErrorFallback({ error, resetErrorBoundary }: FallbackProps) {
  return (
    <div className="error-boundary">
      <div className="error-content">
        <h2>Something went wrong</h2>
        <p>{error?.message}</p>
        <button onClick={resetErrorBoundary} className="error-retry-button">
          Try again
        </button>
      </div>
    </div>
  );
}