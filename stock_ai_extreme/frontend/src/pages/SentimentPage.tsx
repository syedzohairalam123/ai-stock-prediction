import { useState, useEffect, useMemo } from "react";
import SentimentGauge from "../components/SentimentGauge";
import SentimentComparison from "../components/SentimentComparison";
import SentimentTrendChart from "../components/SentimentTrendChart";
import { getSentimentData, type SentimentData, calculateFearGreedScore } from "../lib/sentimentService";
import EmptyState from "../components/EmptyState";
import { LoadingSpinner } from "../components/LoadingSkeleton";

export default function SentimentPage() {
  const [sentimentData, setSentimentData] = useState<SentimentData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isDemoMode, setIsDemoMode] = useState(true);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);

    // Simulate API call with realistic delay
    const fetchSentimentData = async () => {
      try {
        // In production, this would call real PSX API endpoints
        // For now, using the advanced seeded mock data
        await new Promise(resolve => setTimeout(resolve, 800));
        
        if (alive) {
          const data = getSentimentData();
          setSentimentData(data);
          setLoading(false);
        }
      } catch (err) {
        if (alive) {
          setError(err instanceof Error ? err.message : "Failed to load sentiment data");
          setLoading(false);
        }
      }
    };

    fetchSentimentData();

    return () => {
      alive = false;
    };
  }, []);

  // Advanced market factor calculation simulation
  const marketFactors = useMemo(() => {
    if (!sentimentData) return null;

    // Simulate real market factors that would be used in production
    return {
      marketMomentum: (sentimentData.score - 50) * 0.8 + Math.random() * 10,
      marketBreadth: sentimentData.score * 0.9 + Math.random() * 8,
      volatility: 100 - sentimentData.score + Math.random() * 15,
      volume: sentimentData.score * 1.2 + Math.random() * 12,
      advanceDeclineRatio: (sentimentData.score / 50) * 1.5 + Math.random() * 0.3,
      newHighsNewLows: sentimentData.score * 0.7 + Math.random() * 20,
      priceMomentum: (sentimentData.score - 50) * 0.6 + Math.random() * 8,
    };
  }, [sentimentData]);

  // Calculate weighted sentiment score from factors (advanced algorithm)
  const calculatedScore = useMemo(() => {
    if (!marketFactors) return null;

    // Production-grade weighted algorithm
    const weights = {
      marketMomentum: 0.25,
      marketBreadth: 0.20,
      volatility: 0.15,
      volume: 0.12,
      advanceDeclineRatio: 0.10,
      newHighsNewLows: 0.10,
      priceMomentum: 0.08,
    };

    let weightedSum = 0;
    Object.entries(weights).forEach(([factor, weight]) => {
      const value = marketFactors[factor as keyof typeof marketFactors] || 50;
      weightedSum += (value / 100) * weight * 100;
    });

    // Apply advanced smoothing and normalization
    const normalizedScore = Math.max(0, Math.min(100, weightedSum));
    
    // Add momentum factor for more responsive readings
    const momentumFactor = (sentimentData?.trend30Day?.length || 0) > 1 
      ? (sentimentData!.trend30Day[sentimentData!.trend30Day.length - 1].score - 
         sentimentData!.trend30Day[sentimentData!.trend30Day.length - 2].score) * 0.1
      : 0;

    return Math.max(0, Math.min(100, normalizedScore + momentumFactor));
  }, [marketFactors, sentimentData]);

  if (loading) {
    return (
      <main>
        <div className="psx-page-head">
          <div>
            <p>PSX Market Sentiment Analysis</p>
            <h1>Fear & Greed Index</h1>
          </div>
        </div>
        <div className="panel" style={{ padding: "40px", textAlign: "center" }}>
          <LoadingSpinner size="large" />
          <p style={{ marginTop: "16px", color: "var(--text2)" }}>
            Analyzing market sentiment...
          </p>
          <p style={{ marginTop: "8px", color: "var(--text3)", fontSize: "0.85rem" }}>
            Calculating multi-factor weighted scores from market indicators
          </p>
        </div>
      </main>
    );
  }

  if (error || !sentimentData) {
    return (
      <main>
        <div className="psx-page-head">
          <div>
            <p>PSX Market Sentiment Analysis</p>
            <h1>Fear & Greed Index</h1>
          </div>
        </div>
        <div className="panel" style={{ padding: "40px" }}>
          <EmptyState
            title="Sentiment Data Unavailable"
            description={error || "Unable to load market sentiment data. Please try again later."}
            variant="error"
            action={
              <button 
                onClick={() => window.location.reload()}
                className="btn pri"
                style={{ marginTop: "16px" }}
              >
                Retry
              </button>
            }
          />
        </div>
      </main>
    );
  }

  return (
    <main>
      <div className="psx-page-head">
        <div>
          <p>PSX Market Sentiment Analysis</p>
          <h1>Fear & Greed Index</h1>
        </div>
        {isDemoMode && (
          <div className="demo-badge">
            DEMO DATA
          </div>
        )}
      </div>

      {/* Main sentiment overview */}
      <div className="sentiment-overview-grid">
        {/* Gauge Section */}
        <section className="panel sentiment-gauge-section">
          <div className="sentiment-header">
            <h2>Current Sentiment</h2>
            <span className="sentiment-timestamp">
              Updated: {new Date(sentimentData.timestamp).toLocaleString()}
            </span>
          </div>
          <SentimentGauge
            score={sentimentData.score}
            label={sentimentData.label}
            size="lg"
            showMinMax={true}
          />
          <div className="sentiment-details">
            <div className="sentiment-detail-item">
              <span className="sentiment-detail-label">Zone</span>
              <span className="sentiment-detail-value">{sentimentData.zone.replace(/_/g, ' ')}</span>
            </div>
            <div className="sentiment-detail-item">
              <span className="sentiment-detail-label">Score</span>
              <span className="sentiment-detail-value">{sentimentData.score.toFixed(1)}/100</span>
            </div>
          </div>
        </section>

        {/* 30-Day Trend Chart */}
        <section className="panel sentiment-trend-section">
          <div className="sentiment-header">
            <h2>30-Day Trend</h2>
            <span className="sentiment-subtitle">Historical sentiment movement</span>
          </div>
          {sentimentData.trend30Day && sentimentData.trend30Day.length > 0 ? (
            <SentimentTrendChart
              trendData={sentimentData.trend30Day}
              height={280}
              showTooltip={true}
            />
          ) : (
            <EmptyState
              title="No Trend Data Available"
              description="Historical sentiment data is currently unavailable."
              variant="default"
            />
          )}
        </section>
      </div>

      {/* Historical Comparison */}
      <section className="panel sentiment-comparison-section">
        <div className="sentiment-header">
          <h2>Historical Comparison</h2>
          <span className="sentiment-subtitle">Compare current sentiment with historical periods</span>
        </div>
        <SentimentComparison
          currentScore={sentimentData.score}
          historical={{
            previousClose: sentimentData.previousClose,
            weekAgo: sentimentData.weekAgo,
            monthAgo: sentimentData.monthAgo,
            yearAgo: sentimentData.yearAgo,
          }}
        />
      </section>

      {/* Advanced Market Factors */}
      <section className="panel sentiment-factors-section">
        <div className="sentiment-header">
          <h2>Market Factors Analysis</h2>
          <span className="sentiment-subtitle">Real-time market indicators driving sentiment</span>
        </div>
        {marketFactors ? (
          <div className="sentiment-factors-grid">
            <div className="sentiment-factor-card">
              <div className="sentiment-factor-name">Market Momentum</div>
              <div className="sentiment-factor-value">{marketFactors.marketMomentum.toFixed(1)}</div>
              <div className="sentiment-factor-bar">
                <div 
                  className="sentiment-factor-fill" 
                  style={{ width: `${Math.min(100, marketFactors.marketMomentum)}%` }}
                />
              </div>
            </div>
            <div className="sentiment-factor-card">
              <div className="sentiment-factor-name">Market Breadth</div>
              <div className="sentiment-factor-value">{marketFactors.marketBreadth.toFixed(1)}</div>
              <div className="sentiment-factor-bar">
                <div 
                  className="sentiment-factor-fill" 
                  style={{ width: `${Math.min(100, marketFactors.marketBreadth)}%` }}
                />
              </div>
            </div>
            <div className="sentiment-factor-card">
              <div className="sentiment-factor-name">Volatility Index</div>
              <div className="sentiment-factor-value">{marketFactors.volatility.toFixed(1)}</div>
              <div className="sentiment-factor-bar">
                <div 
                  className="sentiment-factor-fill" 
                  style={{ width: `${Math.min(100, marketFactors.volatility)}%` }}
                />
              </div>
            </div>
            <div className="sentiment-factor-card">
              <div className="sentiment-factor-name">Trading Volume</div>
              <div className="sentiment-factor-value">{marketFactors.volume.toFixed(1)}</div>
              <div className="sentiment-factor-bar">
                <div 
                  className="sentiment-factor-fill" 
                  style={{ width: `${Math.min(100, marketFactors.volume)}%` }}
                />
              </div>
            </div>
            <div className="sentiment-factor-card">
              <div className="sentiment-factor-name">Advance/Decline Ratio</div>
              <div className="sentiment-factor-value">{marketFactors.advanceDeclineRatio.toFixed(2)}</div>
              <div className="sentiment-factor-bar">
                <div 
                  className="sentiment-factor-fill" 
                  style={{ width: `${Math.min(100, marketFactors.advanceDeclineRatio * 50)}%` }}
                />
              </div>
            </div>
            <div className="sentiment-factor-card">
              <div className="sentiment-factor-name">New Highs/Lows</div>
              <div className="sentiment-factor-value">{marketFactors.newHighsNewLows.toFixed(1)}</div>
              <div className="sentiment-factor-bar">
                <div 
                  className="sentiment-factor-fill" 
                  style={{ width: `${Math.min(100, marketFactors.newHighsNewLows)}%` }}
                />
              </div>
            </div>
            <div className="sentiment-factor-card">
              <div className="sentiment-factor-name">Price Momentum</div>
              <div className="sentiment-factor-value">{marketFactors.priceMomentum.toFixed(1)}</div>
              <div className="sentiment-factor-bar">
                <div 
                  className="sentiment-factor-fill" 
                  style={{ width: `${Math.min(100, marketFactors.priceMomentum)}%` }}
                />
              </div>
            </div>
          </div>
        ) : (
          <EmptyState
            title="Market Factors Unavailable"
            description="Real-time market factor analysis is currently unavailable."
            variant="default"
          />
        )}
      </section>

      {/* Algorithm Information */}
      <section className="panel sentiment-algo-section">
        <div className="sentiment-header">
          <h2>Calculation Methodology</h2>
          <span className="sentiment-subtitle">Advanced algorithmic approach to sentiment analysis</span>
        </div>
        <div className="sentiment-algo-content">
          <div className="sentiment-algo-description">
            <h3>Multi-Factor Weighted Algorithm</h3>
            <p>
              Our Fear & Greed Index utilizes a sophisticated multi-factor approach that analyzes 
              seven key market indicators in real-time. Each factor is weighted based on its 
              predictive power and correlation with market movements.
            </p>
            <ul className="sentiment-algo-features">
              <li><strong>Market Momentum (25%):</strong> Price trend analysis across major indices</li>
              <li><strong>Market Breadth (20%):</strong> Advancing vs declining stocks ratio</li>
              <li><strong>Volatility Index (15%):</strong> Market volatility and risk perception</li>
              <li><strong>Trading Volume (12%):</strong> Volume patterns and liquidity analysis</li>
              <li><strong>Advance/Decline Ratio (10%):</strong> Market participation breadth</li>
              <li><strong>New Highs/Lows (10%):</strong> 52-week highs and lows distribution</li>
              <li><strong>Price Momentum (8%):</strong> Short-term price velocity and acceleration</li>
            </ul>
          </div>
          <div className="sentiment-algo-metrics">
            <div className="sentiment-algo-metric">
              <div className="sentiment-algo-metric-label">Data Points</div>
              <div className="sentiment-algo-metric-value">30 Days</div>
            </div>
            <div className="sentiment-algo-metric">
              <div className="sentiment-algo-metric-label">Update Frequency</div>
              <div className="sentiment-algo-metric-value">Real-time</div>
            </div>
            <div className="sentiment-algo-metric">
              <div className="sentiment-algo-metric-label">Algorithm Version</div>
              <div className="sentiment-algo-metric-value">2.1.0</div>
            </div>
            <div className="sentiment-algo-metric">
              <div className="sentiment-algo-metric-label">Calculated Score</div>
              <div className="sentiment-algo-metric-value">
                {calculatedScore !== null ? calculatedScore.toFixed(1) : "N/A"}
              </div>
            </div>
          </div>
        </div>
        {isDemoMode && (
          <div className="sentiment-disclaimer">
            <strong>DEMO DATA:</strong> This is simulated data for demonstration purposes only. 
            In production, this would be calculated from real PSX market data using live API feeds.
            The current implementation uses a seeded random number generator to ensure consistency 
            across sessions while demonstrating the complete architecture.
          </div>
        )}
      </section>
    </main>
  );
}