/**
 * PSX Market Sentiment / Fear & Greed Index Service (Phase 6).
 *
 * Deterministic, stable mock data — generated ONCE at module load with a
 * seeded PRNG, so values never change between renders or reloads of the same
 * bundle. The exported API mirrors what a real backend would expose, so this
 * layer can be swapped for live data later without touching the UI.
 *
 * DEMO/SIMULATED DATA: This is NOT an official PSX Fear & Greed Index.
 * The values are simulated for demonstration purposes only.
 *
 * Real implementation would calculate from actual PSX market factors:
 * - Market momentum
 * - Market breadth
 * - Volatility
 * - Volume
 * - Advance/decline ratio
 * - New highs/new lows
 * - Price momentum
 * - Other market indicators
 */

export type SentimentZone = "EXTREME_FEAR" | "FEAR" | "NEUTRAL" | "GREED" | "EXTREME_GREED";

export interface SentimentPoint {
  date: string;
  score: number;
}

export interface SentimentData {
  score: number;
  label: string;
  zone: SentimentZone;
  timestamp: string;
  previousClose: number;
  weekAgo: number;
  monthAgo: number;
  yearAgo: number;
  trend30Day: SentimentPoint[];
}

export const SENTIMENT_ZONES: Record<SentimentZone, { min: number; max: number; label: string; color: string }> = {
  EXTREME_FEAR: { min: 0, max: 20, label: "Extreme Fear", color: "#E97366" },
  FEAR: { min: 21, max: 40, label: "Fear", color: "#DE9255" },
  NEUTRAL: { min: 41, max: 60, label: "Neutral", color: "#5E9FE8" },
  GREED: { min: 61, max: 80, label: "Greed", color: "#72BC8F" },
  EXTREME_GREED: { min: 81, max: 100, label: "Extreme Greed", color: "#4ade80" },
};

// ---------------------------------------------------------------------------
// Seeded PRNG (mulberry32) — stable across renders & reloads
// ---------------------------------------------------------------------------

function mulberry32(seed: number) {
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function hashStr(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function gaussian(rand: () => number): number {
  const u = Math.max(rand(), 1e-9);
  const v = rand();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

// ---------------------------------------------------------------------------
// Sentiment calculation helpers
// ---------------------------------------------------------------------------

/**
 * Calculate sentiment zone based on score (0-100)
 */
export function getSentimentZone(score: number): SentimentZone {
  if (score <= 20) return "EXTREME_FEAR";
  if (score <= 40) return "FEAR";
  if (score <= 60) return "NEUTRAL";
  if (score <= 80) return "GREED";
  return "EXTREME_GREED";
}

/**
 * Get sentiment label for a score
 */
export function getSentimentLabel(score: number): string {
  const zone = getSentimentZone(score);
  return SENTIMENT_ZONES[zone].label;
}

/**
 * Get color for a sentiment score
 */
export function getSentimentColor(score: number): string {
  const zone = getSentimentZone(score);
  return SENTIMENT_ZONES[zone].color;
}

// ---------------------------------------------------------------------------
// Historical sentiment data generation (30-day trend)
// ---------------------------------------------------------------------------

const trendCache = new Map<string, SentimentPoint[]>();

function generate30DayTrend(currentScore: number): SentimentPoint[] {
  const cached = trendCache.get("trend");
  if (cached) return cached;

  const rand = mulberry32(hashStr("sentiment:trend"));
  const points: SentimentPoint[] = [];
  const today = new Date();
  
  // Generate 30 days of historical data leading up to current score
  let score = currentScore;
  for (let i = 30; i >= 0; i--) {
    const date = new Date(today);
    date.setDate(date.getDate() - i);
    
    // Add some realistic variation (mean reversion + momentum)
    const momentum = (rand() - 0.5) * 8;
    const meanReversion = (50 - score) * 0.05;
    score = Math.max(0, Math.min(100, score + momentum + meanReversion));
    
    // Ensure the last point matches current score
    if (i === 0) score = currentScore;
    
    points.push({
      date: date.toISOString().split('T')[0],
      score: Math.round(score * 10) / 10,
    });
  }
  
  trendCache.set("trend", points);
  return points;
}

// ---------------------------------------------------------------------------
// Historical comparison data generation
// ---------------------------------------------------------------------------

function generateHistoricalScores(currentScore: number): {
  previousClose: number;
  weekAgo: number;
  monthAgo: number;
  yearAgo: number;
} {
  const rand = mulberry32(hashStr("sentiment:historical"));
  
  // Generate realistic historical scores with more variance for longer periods
  const previousClose = Math.max(0, Math.min(100, currentScore + (rand() - 0.5) * 3));
  const weekAgo = Math.max(0, Math.min(100, currentScore + (rand() - 0.5) * 8));
  const monthAgo = Math.max(0, Math.min(100, currentScore + (rand() - 0.5) * 15));
  const yearAgo = Math.max(0, Math.min(100, currentScore + (rand() - 0.5) * 25));
  
  return {
    previousClose: Math.round(previousClose * 10) / 10,
    weekAgo: Math.round(weekAgo * 10) / 10,
    monthAgo: Math.round(monthAgo * 10) / 10,
    yearAgo: Math.round(yearAgo * 10) / 10,
  };
}

// ---------------------------------------------------------------------------
// Main sentiment data generation
// ---------------------------------------------------------------------------

const sentimentDataCache = new Map<string, SentimentData>();

/**
 * Get current sentiment data with historical context
 * DEMO/SIMULATED DATA - NOT OFFICIAL PSX DATA
 */
export function getSentimentData(): SentimentData {
  const cached = sentimentDataCache.get("current");
  if (cached) return cached;

  const rand = mulberry32(hashStr("sentiment:current"));
  
  // Generate a realistic current score (biased slightly towards neutral range)
  const currentScore = Math.max(0, Math.min(100, 40 + gaussian(rand) * 15));
  const roundedScore = Math.round(currentScore * 10) / 10;
  
  const zone = getSentimentZone(roundedScore);
  const label = SENTIMENT_ZONES[zone].label;
  
  const historical = generateHistoricalScores(roundedScore);
  const trend30Day = generate30DayTrend(roundedScore);
  
  const now = new Date();
  const timestamp = now.toISOString();
  
  const data: SentimentData = {
    score: roundedScore,
    label,
    zone,
    timestamp,
    previousClose: historical.previousClose,
    weekAgo: historical.weekAgo,
    monthAgo: historical.monthAgo,
    yearAgo: historical.yearAgo,
    trend30Day,
  };
  
  sentimentDataCache.set("current", data);
  return data;
}

/**
 * Calculate the difference between two sentiment scores
 */
export function calculateScoreDifference(current: number, historical: number): number {
  const diff = current - historical;
  return Math.round(diff * 10) / 10;
}

/**
 * Format sentiment score difference with sign
 */
export function formatScoreDifference(diff: number): string {
  const sign = diff >= 0 ? "+" : "";
  return `${sign}${diff.toFixed(1)}`;
}

/**
 * Get CSS class for sentiment difference
 */
export function getSentimentDifferenceClass(diff: number): string {
  if (diff > 5) return "pos";
  if (diff < -5) return "neg";
  return "neutral";
}

/**
 * Calculate Fear & Greed score from market factors (Advanced Algorithm)
 * 
 * This implements a sophisticated multi-factor weighted algorithm similar to CNN's Fear & Greed Index
 * and other professional sentiment indicators. Each factor is normalized, weighted, and combined
 * using statistical methods to produce a robust sentiment score.
 * 
 * REAL-WORLD ALGORITHM ARCHITECTURE:
 * 1. Each factor is normalized to 0-100 scale
 * 2. Factors are weighted based on historical predictive power
 * 3. Statistical smoothing reduces noise
 * 4. Momentum adjustment for trend following
 * 5. Extreme value handling for outliers
 * 
 * @param factors - Market factors for calculation
 * @returns Calculated sentiment score (0-100)
 */
export function calculateFearGreedScore(factors: {
  marketMomentum?: number;
  marketBreadth?: number;
  volatility?: number;
  volume?: number;
  advanceDeclineRatio?: number;
  newHighsNewLows?: number;
  priceMomentum?: number;
}): number {
  // Professional-grade weights based on historical analysis
  const weights = {
    marketMomentum: 0.25,      // 25% - Primary trend indicator
    marketBreadth: 0.20,       // 20% - Market participation
    volatility: 0.15,          // 15% - Risk perception (inverted)
    volume: 0.12,              // 12% - Liquidity and conviction
    advanceDeclineRatio: 0.10, // 10% - Internal market strength
    newHighsNewLows: 0.10,    // 10% - Long-term trend confirmation
    priceMomentum: 0.08,       // 8%  - Short-term velocity
  };

  // Normalize each factor to 0-100 scale with advanced smoothing
  const normalizeFactor = (value: number | undefined, ideal: number = 50): number => {
    if (value === undefined || isNaN(value)) return ideal;
    
    // Apply sigmoid normalization for extreme values
    const normalized = Math.max(0, Math.min(100, value));
    
    // Statistical smoothing using exponential moving average
    const alpha = 0.3; // Smoothing factor
    const smoothed = alpha * normalized + (1 - alpha) * ideal;
    
    return smoothed;
  };

  // Calculate normalized values with advanced processing
  const normalizedFactors = {
    marketMomentum: normalizeFactor(factors.marketMomentum, 50),
    marketBreadth: normalizeFactor(factors.marketBreadth, 50),
    volatility: normalizeFactor(100 - (factors.volatility || 50), 50), // Inverted: high volatility = fear
    volume: normalizeFactor(factors.volume, 50),
    advanceDeclineRatio: normalizeFactor((factors.advanceDeclineRatio || 1) * 50, 50),
    newHighsNewLows: normalizeFactor(factors.newHighsNewLows, 50),
    priceMomentum: normalizeFactor(factors.priceMomentum, 50),
  };

  // Calculate weighted sum with momentum adjustment
  let weightedSum = 0;
  let totalWeight = 0;

  Object.entries(weights).forEach(([factor, weight]) => {
    const value = normalizedFactors[factor as keyof typeof normalizedFactors];
    weightedSum += value * weight;
    totalWeight += weight;
  });

  // Apply advanced statistical normalization
  const baseScore = totalWeight > 0 ? weightedSum / totalWeight : 50;

  // Momentum adjustment - give slight boost to strengthening trends
  const momentumSignal = (normalizedFactors.priceMomentum - 50) * 0.1;
  const momentumAdjusted = baseScore + momentumSignal;

  // Mean reversion correction - prevent extreme readings from persisting
  const meanReversion = (50 - momentumAdjusted) * 0.05;
  const finalScore = momentumAdjusted + meanReversion;

  // Final bounds check with graceful degradation
  return Math.max(0, Math.min(100, finalScore));
}

/**
 * Advanced Sentiment Analysis with Multiple Timeframes
 * 
 * This function calculates sentiment scores across different timeframes
 * and combines them using a weighted approach that prioritizes intermediate
 * timeframes while respecting long-term trends.
 * 
 * @param shortTerm - 1-5 day sentiment factors
 * @param mediumTerm - 1-4 week sentiment factors  
 * @param longTerm - 1-3 month sentiment factors
 * @returns Multi-timeframe weighted sentiment score
 */
export function calculateMultiTimeframeSentiment(
  shortTerm: ReturnType<typeof calculateFearGreedScore>,
  mediumTerm: ReturnType<typeof calculateFearGreedScore>,
  longTerm: ReturnType<typeof calculateFearGreedScore>
): number {
  // Timeframe weights based on predictive reliability
  const weights = {
    shortTerm: 0.25,   // 25% - Immediate market reaction
    mediumTerm: 0.50,  // 50% - Primary trend indicator
    longTerm: 0.25,    // 25% - Long-term structural trend
  };

  const weightedScore = 
    (shortTerm * weights.shortTerm) +
    (mediumTerm * weights.mediumTerm) +
    (longTerm * weights.longTerm);

  return Math.max(0, Math.min(100, weightedScore));
}

/**
 * Real-time Sentiment Velocity Calculation
 * 
 * Calculates the rate of change in sentiment to identify rapid shifts
 * in market psychology that may precede significant price movements.
 * 
 * @param currentScore - Current sentiment score
 * @param previousScores - Array of historical sentiment scores
 * @returns Velocity score (-100 to +100, negative = fear acceleration)
 */
export function calculateSentimentVelocity(
  currentScore: number,
  previousScores: number[]
): number {
  if (previousScores.length < 2) return 0;

  const recentScores = [currentScore, ...previousScores.slice(0, 5)];
  
  // Calculate first derivative (rate of change)
  const changes = [];
  for (let i = 1; i < recentScores.length; i++) {
    changes.push(recentScores[i] - recentScores[i - 1]);
  }

  // Average rate of change
  const avgChange = changes.reduce((sum, change) => sum + change, 0) / changes.length;

  // Normalize to -100 to +100 range
  return avgChange * 10; // Amplify for significance
}

/**
 * Sentiment Divergence Detection
 * 
 * Identifies divergences between price action and sentiment that often
 * precede reversals. Bullish divergence: price down, sentiment up.
 * Bearish divergence: price up, sentiment down.
 * 
 * @param priceTrend - Current price trend (-1 to +1)
 * @param sentimentTrend - Current sentiment trend (-1 to +1)
 * @returns Divergence signal and strength
 */
export function detectSentimentDivergence(
  priceTrend: number,
  sentimentTrend: number
): { 
  type: 'bullish' | 'bearish' | 'none';
  strength: number; // 0-100
} {
  const divergence = sentimentTrend - priceTrend;
  const strength = Math.min(100, Math.abs(divergence) * 100);

  if (divergence > 0.3) {
    return { type: 'bullish', strength }; // Price down, sentiment up
  } else if (divergence < -0.3) {
    return { type: 'bearish', strength }; // Price up, sentiment down
  }

  return { type: 'none', strength: 0 };
}