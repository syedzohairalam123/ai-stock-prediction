"""
Data validators for Phase 16 - Advanced Live Perpetual Futures Analytics + Paper Simulation Engine

This module contains data quality validation pipeline components.
All validators ensure data integrity and freshness before analytics processing.
"""

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple
import logging
from ..schemas import (
    DerivativeQuote, DerivativeInstrument, MarketDepth, DataFreshness,
    DataQualityReport
)

logger = logging.getLogger("neural_market.derivatives.validators")


class DataValidator:
    """
    Data quality validator for derivatives market data.
    
    Every incoming data record must pass:
    SOURCE → SCHEMA VALIDATION → TYPE VALIDATION → TIMESTAMP VALIDATION → 
    NORMALIZATION → FRESHNESS CHECK → ANALYTICS → FRONTEND
    """
    
    def __init__(self, max_age_seconds: int = 300):
        """
        Initialize validator with freshness thresholds.
        
        Args:
            max_age_seconds: Maximum age for data to be considered LIVE
        """
        self.max_age_seconds = max_age_seconds
        self.recent_threshold = timedelta(hours=1)
        self.delayed_threshold = timedelta(hours=24)
        self.stale_threshold = timedelta(days=7)
    
    def validate_quote(self, data: Dict[str, Any], source: str) -> Tuple[bool, DataQualityReport]:
        """
        Validate a derivative quote through the complete quality pipeline.
        
        Args:
            data: Raw quote data from provider
            source: Data source identifier
            
        Returns:
            Tuple of (is_valid, quality_report)
        """
        issues = []
        schema_valid = True
        type_valid = True
        timestamp_valid = True
        normalized = True
        
        # Schema validation
        schema_valid, schema_issues = self._validate_schema(data, DerivativeQuote)
        issues.extend(schema_issues)
        
        # Type validation
        type_valid, type_issues = self._validate_types(data)
        issues.extend(type_issues)
        
        # Timestamp validation
        timestamp_valid, timestamp_issues = self._validate_timestamp(data)
        issues.extend(timestamp_issues)
        
        # Normalization
        normalized, norm_issues = self._normalize_data(data)
        issues.extend(norm_issues)
        
        # Freshness check
        freshness = self._calculate_freshness(data)
        
        # Calculate quality score
        quality_score = self._calculate_quality_score(
            schema_valid, type_valid, timestamp_valid, normalized, freshness
        )
        
        report = DataQualityReport(
            instrument_id=data.get('instrument_id', 'unknown'),
            timestamp=datetime.now(timezone.utc),
            source=source,
            schema_valid=schema_valid,
            type_valid=type_valid,
            timestamp_valid=timestamp_valid,
            normalized=normalized,
            freshness=freshness,
            quality_score=quality_score,
            issues=issues
        )
        
        is_valid = all([schema_valid, type_valid, timestamp_valid, normalized])
        if freshness == DataFreshness.UNAVAILABLE:
            is_valid = False
        
        return is_valid, report
    
    def _validate_schema(self, data: Dict[str, Any], schema_class) -> Tuple[bool, List[str]]:
        """Validate data against schema structure."""
        issues = []
        
        required_fields = ['instrument_id', 'timestamp', 'last_price', 'source']
        for field in required_fields:
            if field not in data:
                issues.append(f"Missing required field: {field}")
        
        # Check numeric fields are numeric
        numeric_fields = ['last_price', 'bid', 'ask', 'spread', 'mark_price', 
                         'index_price', 'change_24h', 'change_percent_24h',
                         'high_24h', 'low_24h', 'volume_24h', 'open_interest', 
                         'funding_rate']
        
        for field in numeric_fields:
            if field in data and data[field] is not None:
                if not isinstance(data[field], (int, float)):
                    try:
                        float(data[field])
                    except (ValueError, TypeError):
                        issues.append(f"Field {field} is not numeric: {data[field]}")
        
        return len(issues) == 0, issues
    
    def _validate_types(self, data: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate data types are correct."""
        issues = []
        
        # String fields
        string_fields = ['instrument_id', 'source', 'data_mode']
        for field in string_fields:
            if field in data and data[field] is not None:
                if not isinstance(data[field], str):
                    issues.append(f"Field {field} should be string, got {type(data[field])}")
        
        # Numeric fields should be finite
        numeric_fields = ['last_price', 'bid', 'ask', 'spread', 'mark_price',
                         'index_price', 'high_24h', 'low_24h', 'volume_24h']
        for field in numeric_fields:
            if field in data and data[field] is not None:
                try:
                    value = float(data[field])
                    if not (-float('inf') < value < float('inf')):
                        issues.append(f"Field {field} is not finite: {value}")
                except (ValueError, TypeError):
                    issues.append(f"Field {field} cannot be converted to float")
        
        return len(issues) == 0, issues
    
    def _validate_timestamp(self, data: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate timestamp is reasonable."""
        issues = []
        
        timestamp = data.get('timestamp')
        if timestamp is None:
            issues.append("Missing timestamp")
            return False, issues
        
        # Convert to datetime if needed
        if isinstance(timestamp, str):
            try:
                timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            except ValueError:
                issues.append(f"Invalid timestamp format: {timestamp}")
                return False, issues
        
        # Check timestamp is not in the future (allow small clock skew)
        now = datetime.now(timezone.utc)
        if timestamp > now + timedelta(minutes=5):
            issues.append(f"Timestamp is in the future: {timestamp}")
        
        # Check timestamp is not too old
        if timestamp < now - timedelta(days=365):
            issues.append(f"Timestamp is too old: {timestamp}")
        
        return len(issues) == 0, issues
    
    def _normalize_data(self, data: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Normalize data to standard format."""
        issues = []
        
        # Ensure timestamp is datetime
        if 'timestamp' in data and isinstance(data['timestamp'], str):
            try:
                data['timestamp'] = datetime.fromisoformat(
                    data['timestamp'].replace('Z', '+00:00')
                )
            except ValueError:
                issues.append("Could not normalize timestamp")
        
        # Ensure numeric fields are float
        numeric_fields = ['last_price', 'bid', 'ask', 'spread', 'mark_price',
                         'index_price', 'change_24h', 'change_percent_24h',
                         'high_24h', 'low_24h', 'volume_24h', 'open_interest',
                         'funding_rate']
        
        for field in numeric_fields:
            if field in data and data[field] is not None:
                try:
                    data[field] = float(data[field])
                except (ValueError, TypeError):
                    issues.append(f"Could not normalize {field} to float")
        
        # Calculate spread if bid and ask exist but spread doesn't
        if 'bid' in data and 'ask' in data and data['bid'] and data['ask']:
            if 'spread' not in data or data['spread'] is None:
                data['spread'] = data['ask'] - data['bid']
        
        # Round numeric fields to reasonable precision
        if 'last_price' in data and data['last_price'] is not None:
            data['last_price'] = round(data['last_price'], 8)
        
        return len(issues) == 0, issues
    
    def _calculate_freshness(self, data: Dict[str, Any]) -> DataFreshness:
        """Calculate data freshness state."""
        timestamp = data.get('timestamp')
        if timestamp is None:
            return DataFreshness.UNAVAILABLE
        
        # Convert to datetime if needed
        if isinstance(timestamp, str):
            try:
                timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            except ValueError:
                return DataFreshness.UNAVAILABLE
        
        now = datetime.now(timezone.utc)
        age = now - timestamp
        
        if age <= timedelta(seconds=self.max_age_seconds):
            return DataFreshness.LIVE
        elif age <= self.recent_threshold:
            return DataFreshness.RECENT
        elif age <= self.delayed_threshold:
            return DataFreshness.DELAYED
        elif age <= self.stale_threshold:
            return DataFreshness.STALE
        else:
            return DataFreshness.UNAVAILABLE
    
    def _calculate_quality_score(self, schema_valid: bool, type_valid: bool,
                                  timestamp_valid: bool, normalized: bool,
                                  freshness: DataFreshness) -> float:
        """Calculate overall quality score (0-1)."""
        score = 0.0
        
        # Schema and type validation are critical
        if schema_valid:
            score += 0.3
        if type_valid:
            score += 0.3
        if timestamp_valid:
            score += 0.2
        if normalized:
            score += 0.1
        
        # Freshness impacts remaining score
        freshness_scores = {
            DataFreshness.LIVE: 0.1,
            DataFreshness.RECENT: 0.08,
            DataFreshness.DELAYED: 0.05,
            DataFreshness.STALE: 0.02,
            DataFreshness.UNAVAILABLE: 0.0
        }
        score += freshness_scores.get(freshness, 0.0)
        
        return min(score, 1.0)


class InstrumentValidator:
    """Validator for derivative instrument data."""
    
    @staticmethod
    def validate_instrument(data: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate instrument data structure."""
        issues = []
        
        required_fields = ['symbol', 'display_name', 'asset_class', 'underlying',
                          'quote_currency', 'exchange', 'tick_size', 'lot_size',
                          'price_precision', 'quantity_precision']
        
        for field in required_fields:
            if field not in data:
                issues.append(f"Missing required field: {field}")
        
        # Validate numeric fields
        numeric_fields = ['tick_size', 'lot_size', 'min_order_size', 'max_order_size']
        for field in numeric_fields:
            if field in data and data[field] is not None:
                try:
                    value = float(data[field])
                    if value <= 0:
                        issues.append(f"Field {field} must be positive: {value}")
                except (ValueError, TypeError):
                    issues.append(f"Field {field} is not numeric")
        
        # Validate precision fields
        precision_fields = ['price_precision', 'quantity_precision']
        for field in precision_fields:
            if field in data and data[field] is not None:
                try:
                    value = int(data[field])
                    if value < 0:
                        issues.append(f"Field {field} must be non-negative: {value}")
                except (ValueError, TypeError):
                    issues.append(f"Field {field} is not integer")
        
        return len(issues) == 0, issues


class MarketDepthValidator:
    """Validator for market depth/order book data."""
    
    @staticmethod
    def validate_market_depth(data: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate market depth data structure."""
        issues = []
        
        required_fields = ['instrument_id', 'timestamp', 'bids', 'asks', 'source']
        for field in required_fields:
            if field not in data:
                issues.append(f"Missing required field: {field}")
        
        # Validate bids and asks are lists
        if 'bids' in data and not isinstance(data['bids'], list):
            issues.append("bids must be a list")
        
        if 'asks' in data and not isinstance(data['asks'], list):
            issues.append("asks must be a list")
        
        # Validate each bid/ask level
        for side in ['bids', 'asks']:
            if side in data and isinstance(data[side], list):
                for i, level in enumerate(data[side]):
                    if not isinstance(level, dict):
                        issues.append(f"{side}[{i}] must be a dict")
                        continue
                    
                    if 'price' not in level or 'quantity' not in level:
                        issues.append(f"{side}[{i}] missing price or quantity")
                        continue
                    
                    try:
                        price = float(level['price'])
                        quantity = float(level['quantity'])
                        if price <= 0 or quantity <= 0:
                            issues.append(f"{side}[{i}] price and quantity must be positive")
                    except (ValueError, TypeError):
                        issues.append(f"{side}[{i}] price and quantity must be numeric")
        
        return len(issues) == 0, issues


class FundingDataValidator:
    """Validator for funding rate data."""
    
    @staticmethod
    def validate_funding_data(data: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate funding rate data structure."""
        issues = []
        
        required_fields = ['instrument_id', 'source']
        for field in required_fields:
            if field not in data:
                issues.append(f"Missing required field: {field}")
        
        # Validate funding rates are numeric
        rate_fields = ['current_funding_rate', 'predicted_funding_rate', 'last_funding_rate']
        for field in rate_fields:
            if field in data and data[field] is not None:
                try:
                    float(data[field])
                except (ValueError, TypeError):
                    issues.append(f"Field {field} must be numeric")
        
        return len(issues) == 0, issues


class OpenInterestValidator:
    """Validator for open interest data."""
    
    @staticmethod
    def validate_open_interest(data: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate open interest data structure."""
        issues = []
        
        required_fields = ['instrument_id', 'source']
        for field in required_fields:
            if field not in data:
                issues.append(f"Missing required field: {field}")
        
        # Validate open interest fields are numeric and non-negative
        oi_fields = ['current_open_interest', 'open_interest_value', 
                    'open_interest_change_24h', 'open_interest_change_percent_24h']
        for field in oi_fields:
            if field in data and data[field] is not None:
                try:
                    value = float(data[field])
                    if 'current_open_interest' in field or 'open_interest_value' in field:
                        if value < 0:
                            issues.append(f"Field {field} must be non-negative: {value}")
                except (ValueError, TypeError):
                    issues.append(f"Field {field} must be numeric")
        
        return len(issues) == 0, issues
