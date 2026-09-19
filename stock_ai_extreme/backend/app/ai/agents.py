"""
AI Agent Architecture

Extensible agent system with specialized agents for different financial tasks.
Each agent focuses on a specific capability and has controlled data access.

SECURITY:
- Agents only access data relevant to their task
- Portfolio agent validates authorization before accessing private data
- No agent can access unrelated private data
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional
from datetime import datetime
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from .context_builder import ContextBuilder
from ..models import AgentTask

logger = structlog.get_logger(__name__)


class BaseAgent(ABC):
    """
    Base class for all specialized agents.
    
    Each agent implements execute() to perform its specific task.
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.context_builder = ContextBuilder(db)
    
    @abstractmethod
    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the agent's task.
        
        Args:
            params: Task parameters
            
        Returns:
            Task result dictionary
        """
        pass
    
    @abstractmethod
    def get_agent_name(self) -> str:
        """Return the agent's name."""
        pass
    
    async def log_task(
        self,
        conversation_id: Optional[int],
        task_type: str,
        status: str,
        input_params: Dict,
        result: Optional[Dict] = None,
        error: Optional[str] = None,
        execution_time_ms: Optional[int] = None,
    ) -> int:
        """Log agent task to database."""
        try:
            task = AgentTask(
                conversation_id=conversation_id,
                task_type=task_type,
                agent_name=self.get_agent_name(),
                status=status,
                input_params=input_params,
                result=result,
                error=error,
                execution_time_ms=execution_time_ms,
                completed_at=datetime.utcnow() if status in ["COMPLETED", "FAILED"] else None,
            )
            self.db.add(task)
            await self.db.commit()
            await self.db.refresh(task)
            return task.id
        except Exception as e:
            logger.error("agent_task_log_error", error=str(e))
            return -1


class MarketDataAgent(BaseAgent):
    """
    Agent for market-level data and analysis.
    
    Capabilities:
    - Market overview
    - Index performance
    - Sector analysis
    - Market movers
    """
    
    def get_agent_name(self) -> str:
        return "MarketDataAgent"
    
    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute market data retrieval and analysis.
        
        Params:
            - task: "overview" | "movers" | "sector_analysis"
            - conversation_id: Optional conversation ID
        """
        start_time = datetime.utcnow()
        task_type = "MARKET_ANALYSIS"
        
        try:
            task = params.get("task", "overview")
            
            # Build market context
            context = await self.context_builder.build_context(
                route="/market",
                include_news=True,
                include_sentiment=True,
            )
            
            result = {
                "agent": self.get_agent_name(),
                "task": task,
                "context": context.get("market_context", {}),
                "timestamp": datetime.utcnow().isoformat(),
            }
            
            execution_time = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            
            await self.log_task(
                conversation_id=params.get("conversation_id"),
                task_type=task_type,
                status="COMPLETED",
                input_params=params,
                result=result,
                execution_time_ms=execution_time,
            )
            
            return result
            
        except Exception as e:
            logger.error("market_data_agent_error", error=str(e))
            execution_time = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            
            await self.log_task(
                conversation_id=params.get("conversation_id"),
                task_type=task_type,
                status="FAILED",
                input_params=params,
                error=str(e),
                execution_time_ms=execution_time,
            )
            
            raise


class StockAnalysisAgent(BaseAgent):
    """
    Agent for stock-specific analysis.
    
    Capabilities:
    - Stock performance analysis
    - Price movement interpretation
    - Technical and fundamental context
    """
    
    def get_agent_name(self) -> str:
        return "StockAnalysisAgent"
    
    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute stock analysis.
        
        Params:
            - symbol: Stock symbol (required)
            - timeframe: Optional timeframe
            - include_news: Whether to include news
            - conversation_id: Optional conversation ID
        """
        start_time = datetime.utcnow()
        task_type = "STOCK_ANALYSIS"
        
        try:
            symbol = params.get("symbol")
            if not symbol:
                raise ValueError("Symbol is required")
            
            # Build stock context
            context = await self.context_builder.build_context(
                route=f"/stock/{symbol}",
                symbol=symbol,
                entity_type="stock",
                timeframe=params.get("timeframe"),
                include_news=params.get("include_news", True),
                include_announcements=True,
                include_sentiment=True,
            )
            
            result = {
                "agent": self.get_agent_name(),
                "symbol": symbol,
                "context": context.get("stock_context", {}),
                "timestamp": datetime.utcnow().isoformat(),
            }
            
            execution_time = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            
            await self.log_task(
                conversation_id=params.get("conversation_id"),
                task_type=task_type,
                status="COMPLETED",
                input_params=params,
                result=result,
                execution_time_ms=execution_time,
            )
            
            return result
            
        except Exception as e:
            logger.error("stock_analysis_agent_error", error=str(e), params=params)
            execution_time = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            
            await self.log_task(
                conversation_id=params.get("conversation_id"),
                task_type=task_type,
                status="FAILED",
                input_params=params,
                error=str(e),
                execution_time_ms=execution_time,
            )
            
            raise


class NewsAgent(BaseAgent):
    """
    Agent for news summarization and analysis.
    
    Capabilities:
    - News summarization
    - Topic extraction
    - Impact analysis
    """
    
    def get_agent_name(self) -> str:
        return "NewsAgent"
    
    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute news analysis.
        
        Params:
            - symbol: Optional symbol to filter news
            - max_items: Maximum news items to analyze
            - conversation_id: Optional conversation ID
        """
        start_time = datetime.utcnow()
        task_type = "NEWS_SUMMARY"
        
        try:
            symbol = params.get("symbol")
            max_items = params.get("max_items", 10)
            
            if symbol:
                # Stock-specific news
                context = await self.context_builder.build_context(
                    route=f"/stock/{symbol}",
                    symbol=symbol,
                    entity_type="stock",
                    include_news=True,
                    max_news_items=max_items,
                )
                news_data = context.get("stock_context", {}).get("recent_news", [])
            else:
                # General news
                context = await self.context_builder._build_news_page_context(
                    max_items=max_items
                )
                news_data = context.get("recent_headlines", [])
            
            result = {
                "agent": self.get_agent_name(),
                "symbol": symbol,
                "news_count": len(news_data),
                "news_data": news_data,
                "timestamp": datetime.utcnow().isoformat(),
            }
            
            execution_time = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            
            await self.log_task(
                conversation_id=params.get("conversation_id"),
                task_type=task_type,
                status="COMPLETED",
                input_params=params,
                result=result,
                execution_time_ms=execution_time,
            )
            
            return result
            
        except Exception as e:
            logger.error("news_agent_error", error=str(e), params=params)
            execution_time = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            
            await self.log_task(
                conversation_id=params.get("conversation_id"),
                task_type=task_type,
                status="FAILED",
                input_params=params,
                error=str(e),
                execution_time_ms=execution_time,
            )
            
            raise


class AnnouncementAgent(BaseAgent):
    """
    Agent for PSX announcement analysis.
    
    Capabilities:
    - Announcement summarization
    - Corporate action interpretation
    - Regulatory filing analysis
    """
    
    def get_agent_name(self) -> str:
        return "AnnouncementAgent"
    
    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute announcement analysis.
        
        Params:
            - symbol: Stock symbol (required)
            - max_items: Maximum announcements to analyze
            - conversation_id: Optional conversation ID
        """
        start_time = datetime.utcnow()
        task_type = "ANNOUNCEMENT_ANALYSIS"
        
        try:
            symbol = params.get("symbol")
            if not symbol:
                raise ValueError("Symbol is required")
            
            max_items = params.get("max_items", 5)
            
            # Get announcements through context builder
            announcements = await self.context_builder._get_relevant_announcements(
                symbol=symbol,
                limit=max_items,
            )
            
            result = {
                "agent": self.get_agent_name(),
                "symbol": symbol,
                "announcements_count": len(announcements),
                "announcements": announcements,
                "timestamp": datetime.utcnow().isoformat(),
            }
            
            execution_time = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            
            await self.log_task(
                conversation_id=params.get("conversation_id"),
                task_type=task_type,
                status="COMPLETED",
                input_params=params,
                result=result,
                execution_time_ms=execution_time,
            )
            
            return result
            
        except Exception as e:
            logger.error("announcement_agent_error", error=str(e), params=params)
            execution_time = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            
            await self.log_task(
                conversation_id=params.get("conversation_id"),
                task_type=task_type,
                status="FAILED",
                input_params=params,
                error=str(e),
                execution_time_ms=execution_time,
            )
            
            raise


class SentimentAgent(BaseAgent):
    """
    Agent for sentiment analysis.
    
    Capabilities:
    - Sentiment score interpretation
    - Trend analysis
    - Market psychology insights
    """
    
    def get_agent_name(self) -> str:
        return "SentimentAgent"
    
    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute sentiment analysis.
        
        Params:
            - symbol: Stock symbol (required)
            - conversation_id: Optional conversation ID
        """
        start_time = datetime.utcnow()
        task_type = "SENTIMENT_ANALYSIS"
        
        try:
            symbol = params.get("symbol")
            if not symbol:
                raise ValueError("Symbol is required")
            
            # Get sentiment through context builder
            sentiment = await self.context_builder._get_sentiment(symbol=symbol)
            
            result = {
                "agent": self.get_agent_name(),
                "symbol": symbol,
                "sentiment": sentiment,
                "timestamp": datetime.utcnow().isoformat(),
            }
            
            execution_time = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            
            await self.log_task(
                conversation_id=params.get("conversation_id"),
                task_type=task_type,
                status="COMPLETED",
                input_params=params,
                result=result,
                execution_time_ms=execution_time,
            )
            
            return result
            
        except Exception as e:
            logger.error("sentiment_agent_error", error=str(e), params=params)
            execution_time = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            
            await self.log_task(
                conversation_id=params.get("conversation_id"),
                task_type=task_type,
                status="FAILED",
                input_params=params,
                error=str(e),
                execution_time_ms=execution_time,
            )
            
            raise


class PortfolioAgent(BaseAgent):
    """
    Agent for portfolio analysis.
    
    SECURITY: Only accesses portfolio data after authorization validation.
    
    Capabilities:
    - Portfolio performance analysis
    - Position analysis
    - Exposure breakdown
    - P&L attribution
    """
    
    def get_agent_name(self) -> str:
        return "PortfolioAgent"
    
    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute portfolio analysis.
        
        SECURITY: Requires user_id and validates authorization.
        
        Params:
            - user_id: User identifier (REQUIRED for authorization)
            - analysis_type: "overview" | "performance" | "exposure"
            - conversation_id: Optional conversation ID
        """
        start_time = datetime.utcnow()
        task_type = "PORTFOLIO_ANALYSIS"
        
        try:
            user_id = params.get("user_id")
            if not user_id:
                raise ValueError("User ID required for portfolio access (not authorized)")
            
            # Build portfolio context (with authorization)
            portfolio_context = await self.context_builder._build_portfolio_context(
                user_id=user_id
            )
            
            if "error" in portfolio_context:
                raise ValueError(portfolio_context["error"])
            
            result = {
                "agent": self.get_agent_name(),
                "analysis_type": params.get("analysis_type", "overview"),
                "portfolio": portfolio_context,
                "timestamp": datetime.utcnow().isoformat(),
            }
            
            execution_time = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            
            await self.log_task(
                conversation_id=params.get("conversation_id"),
                task_type=task_type,
                status="COMPLETED",
                input_params={"analysis_type": params.get("analysis_type")},  # Don't log user_id
                result={"summary": f"{portfolio_context['positions_count']} positions"},  # Don't log full portfolio
                execution_time_ms=execution_time,
            )
            
            return result
            
        except Exception as e:
            logger.error("portfolio_agent_error", error=str(e))
            execution_time = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            
            await self.log_task(
                conversation_id=params.get("conversation_id"),
                task_type=task_type,
                status="FAILED",
                input_params={"analysis_type": params.get("analysis_type", "unknown")},
                error=str(e),
                execution_time_ms=execution_time,
            )
            
            raise


class ComparisonAgent(BaseAgent):
    """
    Agent for stock comparison analysis.
    
    Capabilities:
    - Multi-stock comparison
    - Relative performance
    - Sector comparison
    - Fundamental comparison
    """
    
    def get_agent_name(self) -> str:
        return "ComparisonAgent"
    
    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute stock comparison.
        
        Params:
            - symbols: List of symbols to compare (required)
            - include_news: Whether to include news
            - conversation_id: Optional conversation ID
        """
        start_time = datetime.utcnow()
        task_type = "STOCK_COMPARISON"
        
        try:
            symbols = params.get("symbols", [])
            if not symbols or len(symbols) < 2:
                raise ValueError("At least 2 symbols required for comparison")
            
            # Import here to avoid circular dependency
            from .context_builder import build_comparison_context
            
            # Build comparison context
            comparison_context = await build_comparison_context(
                db=self.db,
                symbols=symbols,
                include_news=params.get("include_news", True),
                include_sentiment=True,
            )
            
            result = {
                "agent": self.get_agent_name(),
                "symbols": symbols,
                "comparison": comparison_context,
                "timestamp": datetime.utcnow().isoformat(),
            }
            
            execution_time = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            
            await self.log_task(
                conversation_id=params.get("conversation_id"),
                task_type=task_type,
                status="COMPLETED",
                input_params=params,
                result={"symbols": symbols, "data_points": len(comparison_context.get("data", {}))},
                execution_time_ms=execution_time,
            )
            
            return result
            
        except Exception as e:
            logger.error("comparison_agent_error", error=str(e), params=params)
            execution_time = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            
            await self.log_task(
                conversation_id=params.get("conversation_id"),
                task_type=task_type,
                status="FAILED",
                input_params=params,
                error=str(e),
                execution_time_ms=execution_time,
            )
            
            raise


#: Keyword groups per capability, in match order: the first group that hits
#: wins, so more specific asks sit above the general ones. A question about
#: the user's own book ("which holding…", "my exposure…") is a portfolio
#: question even when it names a symbol, hence the explicit possessive forms.
INTENT_KEYWORDS: tuple = (
    (
        "comparison",
        ("compare", "compared to", "comparison", "versus", " vs ", "difference between", "relative to"),
    ),
    (
        "portfolio",
        (
            "portfolio", "my holding", "holdings", "my position", "my positions",
            "my stocks", "my exposure", "exposure", "my p/l", "my p&l", "pnl",
            "my profit", "my loss", "concentration", "cost basis", "average cost",
            "unrealised", "unrealized",
        ),
    ),
    ("announcement", ("announcement", "announcements", "filing", "filings", "corporate action", "notice of meeting")),
    ("news", ("news", "headline", "headlines", "articles", "in the press")),
    ("sentiment", ("sentiment", "feeling", "mood", "psychology", "bullish or bearish")),
)


class AgentRouter:
    """
    Routes user requests to appropriate specialized agents.
    
    Analyzes user intent and selects the best agent(s) to handle the request.
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.agents = {
            "market": MarketDataAgent(db),
            "stock": StockAnalysisAgent(db),
            "news": NewsAgent(db),
            "announcement": AnnouncementAgent(db),
            "sentiment": SentimentAgent(db),
            "portfolio": PortfolioAgent(db),
            "comparison": ComparisonAgent(db),
        }
    
    def detect_intent(self, question: str, context: Dict[str, Any]) -> str:
        """
        Detect user intent from question and context.

        Returns the agent type: ``market``, ``stock``, ``news``, ``announcement``,
        ``sentiment``, ``portfolio`` or ``comparison``.

        Pure function — no database access — so it can run before any data is
        fetched and be unit-tested directly.
        """
        padded = f" {question.lower().strip()} "

        for intent, keywords in INTENT_KEYWORDS:
            if any(keyword in padded for keyword in keywords):
                return intent

        # A statement about the user's own book implied by the page they are on.
        if context.get("page_type") == "portfolio":
            return "portfolio"

        # Stock detection (if a symbol is in context)
        if context.get("symbol") and context.get("entity_type") == "stock":
            return "stock"
        if context.get("entity_type") == "index":
            return "market"

        # Market detection (default for general questions)
        return "market"
    
    async def route_request(
        self,
        question: str,
        context: Dict[str, Any],
        conversation_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Route user request to appropriate agent.
        
        Args:
            question: User's question
            context: Context from ContextBuilder
            conversation_id: Optional conversation ID
            
        Returns:
            Agent execution result
        """
        intent = self.detect_intent(question, context)
        agent = self.agents[intent]
        
        logger.info("routing_request", intent=intent, agent=agent.get_agent_name())
        
        # Build agent parameters from context
        params = {"conversation_id": conversation_id}
        
        if intent == "stock" and context.get("symbol"):
            params["symbol"] = context["symbol"]
            params["timeframe"] = context.get("timeframe")
        elif intent == "portfolio":
            # For portfolio, user_id must be provided (after authentication)
            params["user_id"] = context.get("user_id")
        elif intent == "comparison":
            # Extract symbols from question or context
            # This is a simplified example - real implementation would be more sophisticated
            import re
            symbols = re.findall(r'\b([A-Z]{2,6})\b', question.upper())
            params["symbols"] = list(set(symbols))[:5]  # Limit to 5 symbols
        
        # Execute agent
        return await agent.execute(params)
