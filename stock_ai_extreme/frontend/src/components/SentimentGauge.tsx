import { useMemo } from "react";
import { getSentimentColor, getSentimentLabel, SENTIMENT_ZONES } from "../lib/sentimentService";

interface SentimentGaugeProps {
  score: number;
  label?: string;
  size?: "sm" | "md" | "lg";
  showMinMax?: boolean;
}

export default function SentimentGauge({
  score,
  label,
  size = "md",
  showMinMax = true,
}: SentimentGaugeProps) {
  const displayLabel = label || getSentimentLabel(score);
  const color = getSentimentColor(score);

  // Calculate needle rotation based on score (0-100 maps to -90deg to +90deg)
  const needleRotation = useMemo(() => {
    return (score / 100) * 180 - 90;
  }, [score]);

  // Size configurations
  const sizeConfig = {
    sm: { width: 200, height: 110, scoreSize: 28, labelSize: 11 },
    md: { width: 280, height: 150, scoreSize: 44, labelSize: 13 },
    lg: { width: 360, height: 190, scoreSize: 56, labelSize: 15 },
  };

  const config = sizeConfig[size];

  return (
    <div className="sentiment-gauge-container">
      <svg
        width={config.width}
        height={config.height}
        viewBox={`0 0 ${config.width} ${config.height}`}
        className="sentiment-gauge"
      >
        {/* Background arc */}
        <defs>
          <linearGradient id="gaugeGradient" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor={SENTIMENT_ZONES.EXTREME_FEAR.color} />
            <stop offset="25%" stopColor={SENTIMENT_ZONES.FEAR.color} />
            <stop offset="50%" stopColor={SENTIMENT_ZONES.NEUTRAL.color} />
            <stop offset="75%" stopColor={SENTIMENT_ZONES.GREED.color} />
            <stop offset="100%" stopColor={SENTIMENT_ZONES.EXTREME_GREED.color} />
          </linearGradient>
        </defs>

        {/* Semi-circular gauge background */}
        <path
          d={`M ${config.width * 0.1} ${config.height * 0.8} 
              A ${config.width * 0.4} ${config.width * 0.4} 0 0 1 ${config.width * 0.9} ${config.height * 0.8}`}
          fill="none"
          stroke="rgba(255,255,255,0.1)"
          strokeWidth="20"
          strokeLinecap="round"
        />

        {/* Colored gauge arc */}
        <path
          d={`M ${config.width * 0.1} ${config.height * 0.8} 
              A ${config.width * 0.4} ${config.width * 0.4} 0 0 1 ${config.width * 0.9} ${config.height * 0.8}`}
          fill="none"
          stroke="url(#gaugeGradient)"
          strokeWidth="20"
          strokeLinecap="round"
          opacity="0.8"
        />

        {/* Zone markers */}
        {[0, 25, 50, 75, 100].map((markerScore) => {
          const angle = (markerScore / 100) * 180 - 90;
          const radians = (angle * Math.PI) / 180;
          const centerX = config.width / 2;
          const centerY = config.height * 0.8;
          const radius = config.width * 0.4 + 15;
          const x = centerX + radius * Math.cos(radians);
          const y = centerY + radius * Math.sin(radians);

          return (
            <g key={markerScore}>
              <circle
                cx={x}
                cy={y}
                r="3"
                fill="rgba(255,255,255,0.5)"
              />
              {showMinMax && (markerScore === 0 || markerScore === 100) && (
                <text
                  x={x}
                  y={y + 20}
                  textAnchor="middle"
                  fill="rgba(255,255,255,0.6)"
                  fontSize="11"
                  fontWeight="500"
                >
                  {markerScore}
                </text>
              )}
            </g>
          );
        })}

        {/* Needle */}
        <g
          transform={`rotate(${needleRotation}, ${config.width / 2}, ${config.height * 0.8})`}
          style={{ transition: "transform 0.5s cubic-bezier(0.4, 0, 0.2, 1)" }}
        >
          <line
            x1={config.width / 2}
            y1={config.height * 0.8}
            x2={config.width / 2}
            y2={config.height * 0.8 - config.width * 0.35}
            stroke="#ffffff"
            strokeWidth="3"
            strokeLinecap="round"
          />
          <circle
            cx={config.width / 2}
            cy={config.height * 0.8}
            r="8"
            fill="#ffffff"
          />
        </g>
      </svg>

      {/* Score and label display */}
      <div className="sentiment-gauge-display">
        <div
          className="sentiment-gauge-score"
          style={{ fontSize: `${config.scoreSize}px`, color }}
        >
          {score.toFixed(0)}
        </div>
        <div
          className="sentiment-gauge-label"
          style={{ fontSize: `${config.labelSize}px`, color }}
        >
          {displayLabel.toUpperCase()}
        </div>
      </div>
    </div>
  );
}