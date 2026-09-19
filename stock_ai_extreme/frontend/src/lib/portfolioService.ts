/**
 * Phase 9 — Portfolio Service
 * 
 * Frontend service for portfolio and transaction management with comprehensive TypeScript types.
 */

import axios from "./axios";

// ============================================================================
// TYPE DEFINITIONS
// ============================================================================

export interface Transaction {
  id: number;
  user_id: string | null;
  symbol: string;
  transaction_type: "BUY" | "SELL";
  quantity: number;
  price: number;
  fees: number;
  total_amount: number;
  transaction_date: string;
  notes: string | null;
  broker: string | null;
  account: string | null;
  created_at: string;
  updated_at: string;
}

export interface CreateTransactionRequest {
  symbol: string;
  transaction_type: "BUY" | "SELL";
  quantity: number;
  price: number;
  fees?: number;
  transaction_date: string;
  notes?: string;
  broker?: string;
  account?: string;
}

export interface Position {
  symbol: string;
  quantity: number;
  average_cost: number;
  total_cost: number;
  current_price: number;
  market_value: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
  realized_pnl: number;
  total_return: number;
  allocation_pct: number;
}

export interface PortfolioSummary {
  num_positions: number;
  total_cost_basis: number;
  total_market_value: number;
  total_realized_pnl: number;
  total_unrealized_pnl: number;
  total_pnl: number;
  total_return_pct: number;
}

export interface PortfolioResponse {
  positions: Position[];
  summary: PortfolioSummary;
  method?: string;
  disclaimer?: string;
}

export interface TransactionsResponse {
  transactions: Transaction[];
  count: number;
}

// Popular Stocks
export interface StockTrend {
  date: string;
  price: number;
}

export interface PopularStock {
  symbol: string;
  name: string;
  price: number | null;
  change: number | null;
  change_pct: number | null;
  sector: string | null;
  industry: string | null;
  market_cap: number | null;
  trend: StockTrend[];
  source: string;
  timestamp: string;
}

export interface PopularStocksResponse {
  stocks: PopularStock[];
  count: number;
  requested?: number;
  unavailable?: { symbol: string; reason: string }[];
  category: string | null;
  categories: string[];
  timestamp: string;
}

export interface StockCategory {
  id: string;
  name: string;
  count: number;
}

export interface CategoriesResponse {
  categories: StockCategory[];
}

// Watchlist
export interface WatchlistItem {
  id: number;
  ticker: string;
  note: string | null;
  added_at: string;
  sort_order?: number;
}

/**
 * Portfolio Service Class
 */
class PortfolioServiceClass {
  // ============================================================================
  // TRANSACTIONS
  // ============================================================================

  async createTransaction(data: CreateTransactionRequest): Promise<Transaction> {
    const response = await axios.post<Transaction>("/api/portfolio/transactions", data);
    return response.data;
  }

  async listTransactions(
    symbol?: string,
    transactionType?: "BUY" | "SELL",
    limit: number = 500
  ): Promise<TransactionsResponse> {
    const params = new URLSearchParams();
    if (symbol) params.append("symbol", symbol);
    if (transactionType) params.append("transaction_type", transactionType);
    params.append("limit", limit.toString());

    const response = await axios.get<TransactionsResponse>(
      `/api/portfolio/transactions?${params.toString()}`
    );
    return response.data;
  }

  async getTransaction(id: number): Promise<Transaction> {
    const response = await axios.get<Transaction>(`/api/portfolio/transactions/${id}`);
    return response.data;
  }

  async deleteTransaction(id: number): Promise<{ deleted: number }> {
    const response = await axios.delete<{ deleted: number }>(
      `/api/portfolio/transactions/${id}`
    );
    return response.data;
  }

  // ============================================================================
  // POSITIONS & SUMMARY
  // ============================================================================

  async getPositions(method: "fifo" | "weighted_average" = "weighted_average"): Promise<PortfolioResponse> {
    const response = await axios.get<PortfolioResponse>(
      `/api/portfolio/positions?method=${method}`
    );
    return response.data;
  }

  async getPortfolioSummary(): Promise<PortfolioResponse> {
    const response = await axios.get<PortfolioResponse>("/api/portfolio/summary");
    return response.data;
  }

  // ============================================================================
  // POPULAR STOCKS
  // ============================================================================

  async getPopularStocks(category?: string, limit: number = 20): Promise<PopularStocksResponse> {
    const params = new URLSearchParams();
    if (category) params.append("category", category);
    params.append("limit", limit.toString());

    const response = await axios.get<PopularStocksResponse>(
      `/api/stocks/popular?${params.toString()}`
    );
    return response.data;
  }

  async getStockCategories(): Promise<CategoriesResponse> {
    const response = await axios.get<CategoriesResponse>("/api/stocks/categories");
    return response.data;
  }

  // ============================================================================
  // WATCHLIST
  // ============================================================================

  async getWatchlist(): Promise<WatchlistItem[]> {
    const response = await axios.get<WatchlistItem[]>("/api/watchlist");
    return response.data;
  }

  async addToWatchlist(ticker: string, note?: string): Promise<WatchlistItem> {
    const response = await axios.post<WatchlistItem>("/api/watchlist", {
      ticker,
      note,
    });
    return response.data;
  }

  async removeFromWatchlist(ticker: string): Promise<{ deleted: boolean }> {
    const response = await axios.delete<{ deleted: boolean }>(
      `/api/watchlist/${ticker}`
    );
    return response.data;
  }

  /** Phase 9: persist a manual watchlist display order. */
  async reorderWatchlist(ids: Array<string | number>): Promise<WatchlistItem[]> {
    const response = await axios.post<{ items: WatchlistItem[] }>(
      "/api/watchlist/reorder",
      { ids }
    );
    return response.data.items;
  }

  /** Phase 9: set or clear the note on a watchlist item. */
  async setWatchlistNote(ticker: string, note: string | null): Promise<WatchlistItem> {
    const response = await axios.patch<WatchlistItem>(
      `/api/watchlist/${encodeURIComponent(ticker)}`,
      { note }
    );
    return response.data;
  }

  // ============================================================================
  // UTILITY METHODS
  // ============================================================================

  /**
   * Format currency value
   */
  formatCurrency(amount: number, currency: string = "PKR"): string {
    return `${currency} ${amount.toLocaleString("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })}`;
  }

  /**
   * Format percentage
   */
  formatPercentage(value: number, showSign: boolean = true): string {
    const sign = value > 0 && showSign ? "+" : "";
    return `${sign}${value.toFixed(2)}%`;
  }

  /**
   * Get color class for P&L values
   */
  getPnLColorClass(value: number): string {
    if (value > 0) return "text-green-600";
    if (value < 0) return "text-red-600";
    return "text-gray-600";
  }

  /**
   * Calculate portfolio metrics
   */
  calculateMetrics(positions: Position[]) {
    const totalValue = positions.reduce((sum, p) => sum + p.market_value, 0);
    const totalCost = positions.reduce((sum, p) => sum + p.total_cost, 0);
    const totalPnL = positions.reduce((sum, p) => sum + p.unrealized_pnl, 0);

    return {
      totalValue,
      totalCost,
      totalPnL,
      totalReturn: totalCost > 0 ? (totalPnL / totalCost) * 100 : 0,
    };
  }
}

// Export singleton instance
export const PortfolioService = new PortfolioServiceClass();
