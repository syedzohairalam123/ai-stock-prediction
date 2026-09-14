import { getSentimentLabel, getSentimentColor, formatScoreDifference, getSentimentDifferenceClass } from "../lib/sentimentService";

interface HistoricalData {
  previousClose: number;
  weekAgo: number;
  monthAgo: number;
  yearAgo: number;
}

interface SentimentComparisonProps {
  currentScore: number;
  historical: HistoricalData;
}

interface ComparisonItem {
  label: string;
  score: number;
  isCurrent?: boolean;
}

export default function SentimentComparison({ currentScore, historical }: SentimentComparisonProps) {
  const comparisonItems: ComparisonItem[] = [
    { label: "Current", score: currentScore, isCurrent: true },
    { label: "Prev Close", score: historical.previousClose },
    { label: "1 Week Ago", score: historical.weekAgo },
    { label: "1 Month Ago", score: historical.monthAgo },
    { label: "1 Year Ago", score: historical.yearAgo },
  ];

  return (
    <div className="sentiment-comparison">
      <h3 className="sentiment-comparison-title">Historical Comparison</h3>
      <div className="sentiment-comparison-grid">
        {comparisonItems.map((item) => {
          const sentimentLabel = getSentimentLabel(item.score);
          const sentimentColor = getSentimentColor(item.score);
          const difference = item.isCurrent ? 0 : currentScore - item.score;
          const diffFormatted = item.isCurrent ? "—" : formatScoreDifference(difference);
          const diffClass = item.isCurrent ? "neutral" : getSentimentDifferenceClass(difference);

          return (
            <div
              key={item.label}
              className={`sentiment-comparison-item ${item.isCurrent ? "current" : ""}`}
            >
              <div className="sentiment-comparison-label">{item.label}</div>
              <div className="sentiment-comparison-score" style={{ color: sentimentColor }}>
                {item.score.toFixed(0)}
              </div>
              <div
                className="sentiment-comparison-sentiment"
                style={{ color: sentimentColor }}
              >
                {sentimentLabel}
              </div>
              {!item.isCurrent && (
                <div className={`sentiment-comparison-diff ${diffClass}`}>
                  {diffFormatted}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}