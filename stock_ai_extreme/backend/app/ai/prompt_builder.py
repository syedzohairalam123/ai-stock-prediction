"""
Prompt Builder Service

Creates structured prompts for AI financial assistant. Separates system instructions,
context, user questions, and response rules for consistent, high-quality responses.

CRITICAL RULES:
- Distinguish FACT from INTERPRETATION
- Never claim "guaranteed profit" or "certain price increase"
- Never present interpretation as fact
- Never manufacture unavailable data
- Cite sources when using news/announcements
"""
from typing import Dict, List, Any, Optional
import json


class PromptBuilder:
    """
    Builds structured prompts for financial AI assistant.
    
    Maintains separation between:
    - SYSTEM INSTRUCTIONS: Who the assistant is, what it can do
    - USER QUESTION: What the user asked
    - MARKET CONTEXT: Current market state
    - DATA CONTEXT: Specific stock/news/announcement data
    - RESPONSE RULES: How to format and present information
    """
    
    SYSTEM_INSTRUCTIONS = """You are an advanced AI financial assistant for the Pakistan Stock Exchange (PSX).

Your capabilities:
- Market research and analysis
- Stock analysis and interpretation
- News and announcement summarization
- Sentiment interpretation
- Portfolio analysis (when authorized)
- Stock comparison and relative analysis

Your responsibilities:
- Provide factual, data-driven insights
- Clearly label interpretations vs. facts
- Cite sources when using news or announcements
- Never guarantee profits or certain outcomes
- Never manufacture data that isn't provided
- Distinguish between what you know and what you're inferring

Your knowledge base:
- Pakistan Stock Exchange (PSX) stocks and indices
- KSE100, KSE30, and other major indices
- Market sentiment and trends
- Corporate announcements and regulatory filings
- Financial news from Pakistani and international sources
- Technical and fundamental analysis concepts

When you don't have data:
- Say "I don't have current data for..."
- Don't invent numbers or facts
- Suggest what data would be needed

Response format:
- Use clear sections for complex analysis
- Present numbers with proper formatting (PKR, percentages)
- Use bullet points for lists
- Keep responses focused and actionable
"""
    
    FINANCIAL_RESPONSE_RULES = """
CRITICAL RESPONSE RULES:

1. FACT vs INTERPRETATION:
   - FACT: "OGDC closed at PKR 95.50, down 2.3%"
   - INTERPRETATION: "Based on the price movement and news, one possible interpretation is..."
   - Always label which is which

2. UNCERTAINTY:
   - Use: "suggests", "indicates", "may", "could", "one interpretation"
   - Avoid: "will", "certainly", "guaranteed", "definitely"

3. RISK DISCLOSURE:
   - Never claim: "Guaranteed profit", "Risk-free trade", "Certain price increase"
   - Always acknowledge: Market risk, information limitations, analysis uncertainty

4. DATA INTEGRITY:
   - Only use data provided in the context
   - If data is missing: "I don't have current [X] data"
   - If data is old: Note the timestamp/date

5. SOURCE CITATION:
   - When using news: Mention the source and date
   - When using announcements: Reference the announcement type and date
   - When using sentiment: Note it's derived from analysis, not a prediction

6. PORTFOLIO ADVICE:
   - Use: "Based on your holdings...", "Consider reviewing...", "You may want to..."
   - Avoid: "You must buy", "Sell immediately", "This will definitely..."

7. COMPARISON:
   - Only compare available metrics
   - Note when data is missing for fair comparison
   - Explain context differences (sectors, size, market cap)

8. MARKET TONE:
   - Structure: SUMMARY → KEY DATA → WHAT CHANGED → POSSIBLE DRIVERS → RISKS
   - Clearly label: What's factual vs. what's interpretation

9. FORMATTING:
   - Numbers: Use PKR for Pakistani stocks, proper separators (1,234.56)
   - Percentages: One decimal place (2.3%)
   - Dates: Clear format (Jan 15, 2025)
   - Changes: Show direction clearly (+2.3% or -1.5%)

10. PROVENANCE LABELS (required):
   Start each key statement with exactly one of these markers so the reader can
   never mistake a reading for a measurement:
   - [FACT] for values taken directly from the supplied data
   - [CALCULATION] for figures you derived from that data (state the formula)
   - [INTERPRETATION] for what the data might mean
   - [ESTIMATE] for anything forward-looking or approximate
   - [USER-SUPPLIED] for information the user provided that is not in the data

11. SOURCES LINE:
   End every answer that used news, announcements, sentiment or market records
   with a final line: `Sources: <short list>`.
   - List only records that appear in the CONTEXT DATA above.
   - Quote their exact titles/publishers/dates as given.
   - Never invent a source, URL, headline or figure.
   - If you used no external records, write `Sources: none (answer uses supplied market data only)`.

12. MISSING DATA:
   If a field is marked UNAVAILABLE, say so plainly. Do not estimate a
   replacement, and do not compare two symbols on a field only one of them has.
"""
    
    def __init__(self):
        pass
    
    def build_messages(
        self,
        user_question: str,
        context: Dict[str, Any],
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> List[Dict[str, str]]:
        """
        Build complete message list for AI provider.
        
        Args:
            user_question: The user's question
            context: Context built by ContextBuilder
            conversation_history: Previous messages in conversation (optional)
            
        Returns:
            List of message dicts with 'role' and 'content' keys
        """
        messages = []
        
        # System message with instructions and rules
        system_content = self._build_system_message(context)
        messages.append({"role": "system", "content": system_content})
        
        # Add conversation history (if any)
        if conversation_history:
            # Limit history to prevent token overflow
            recent_history = conversation_history[-10:]  # Last 10 exchanges
            for msg in recent_history:
                if msg["role"] in ["user", "assistant"]:
                    messages.append(msg)
        
        # Add current user question with context
        user_content = self._build_user_message(user_question, context)
        messages.append({"role": "user", "content": user_content})
        
        return messages
    
    def _build_system_message(self, context: Dict[str, Any]) -> str:
        """Build system message with instructions and current context awareness."""
        parts = [
            self.SYSTEM_INSTRUCTIONS,
            "",
            self.FINANCIAL_RESPONSE_RULES,
            "",
            "CURRENT CONTEXT:",
        ]
        
        # Add context awareness
        page_type = context.get("page_type", "unknown")
        parts.append(f"- User is viewing: {page_type}")
        
        if context.get("symbol"):
            entity_type = context.get("entity_type", "stock")
            parts.append(f"- Current {entity_type}: {context['symbol']}")
        
        if context.get("timeframe"):
            parts.append(f"- Timeframe: {context['timeframe']}")
        
        # Add available data sources
        parts.append("")
        parts.append("AVAILABLE DATA:")
        
        if context.get("stock_context"):
            stock_ctx = context["stock_context"]
            if stock_ctx.get("recent_news"):
                parts.append(f"- {len(stock_ctx['recent_news'])} recent news articles")
            if stock_ctx.get("recent_announcements"):
                parts.append(
                    f"- {len(stock_ctx['recent_announcements'])} recent announcements"
                )
            if stock_ctx.get("sentiment"):
                parts.append("- Sentiment analysis data")
        
        if context.get("portfolio_context"):
            parts.append("- User's portfolio holdings (AUTHORIZED)")
        
        if context.get("market_context"):
            parts.append("- Market overview data")
        
        return "\n".join(parts)
    
    def _build_user_message(self, question: str, context: Dict[str, Any]) -> str:
        """Build user message with question and relevant context data."""
        parts = [
            "USER QUESTION:",
            question,
            "",
            "CONTEXT DATA:",
        ]
        
        # Add relevant context data in structured format
        context_data = self._format_context_data(context)
        parts.append(context_data)
        
        return "\n".join(parts)
    
    def _format_context_data(self, context: Dict[str, Any]) -> str:
        """Format context data for inclusion in prompt.

        Every field is read with ``.get`` and formatted defensively: a missing
        or renamed key must degrade to "data unavailable", never raise. (An
        earlier version indexed keys that the context builder never produced —
        ``change_pct`` and ``value`` — so every market and portfolio prompt
        failed to build at all.)
        """
        parts: List[str] = []

        # ---- Stock context ----
        if stock_ctx := context.get("stock_context"):
            symbol = stock_ctx.get("symbol", context.get("symbol", "?"))
            parts.append(f"\nSTOCK: {symbol}")

            quote_bits = self._format_quote(stock_ctx)
            if quote_bits:
                parts.append(f"QUOTE: {quote_bits}")

            if news := stock_ctx.get("recent_news"):
                parts.append("\nRECENT NEWS:")
                for item in news:
                    parts.append(
                        f"- [{item.get('published_at') or 'date unknown'}] "
                        f"{item.get('publisher') or item.get('source') or 'unknown source'}: "
                        f"{item.get('title', '')}"
                    )
                    if item.get("excerpt"):
                        parts.append(f"  {str(item['excerpt'])[:200]}...")
            else:
                parts.append("RECENT NEWS: none available in this context")

            if announcements := stock_ctx.get("recent_announcements"):
                parts.append("\nRECENT ANNOUNCEMENTS:")
                for ann in announcements:
                    parts.append(
                        f"- [{ann.get('date') or 'date unknown'}] "
                        f"{ann.get('type') or 'filing'}: {ann.get('title', '')}"
                    )

            if sentiment := stock_ctx.get("sentiment"):
                parts.append(f"\nSENTIMENT: {self._format_sentiment(sentiment)}")

        # ---- Index context ----
        if index_ctx := context.get("index_context"):
            symbol = index_ctx.get("symbol", context.get("symbol", "?"))
            parts.append(f"\nINDEX: {symbol}")
            quote_bits = self._format_quote(index_ctx)
            if quote_bits:
                parts.append(f"QUOTE: {quote_bits}")
            if news := index_ctx.get("recent_news"):
                parts.append("\nINDEX NEWS:")
                for item in news:
                    parts.append(f"- {item.get('title', '')}")
            if sentiment := index_ctx.get("sentiment"):
                parts.append(f"SENTIMENT: {self._format_sentiment(sentiment)}")

        # ---- Market context ----
        if market_ctx := context.get("market_context"):
            parts.append("\nMARKET OVERVIEW:")
            indices = market_ctx.get("indices") or {}
            if indices:
                for idx_name, idx_data in indices.items():
                    if not isinstance(idx_data, dict):
                        continue
                    last = idx_data.get("price", idx_data.get("last"))
                    change_pct = idx_data.get("change_percent", idx_data.get("change_pct"))
                    if last is None:
                        parts.append(f"- {idx_name}: UNAVAILABLE from the data provider")
                    elif change_pct is None:
                        parts.append(f"- {idx_name}: {last} (change unavailable)")
                    else:
                        parts.append(f"- {idx_name}: {last} ({change_pct:+.2f}%)")
            else:
                parts.append("- index data unavailable")
            if session := market_ctx.get("market_status"):
                parts.append(
                    f"- Exchange session window: {session} "
                    "(schedule-based, not a live trading feed)"
                )
            if tone := market_ctx.get("headline_tone"):
                aggregate = tone.get("aggregate_sentiment") or {}
                if aggregate:
                    parts.append(
                        "- MARKET TONE (from the app's stored news-desk headlines): "
                        f"{aggregate.get('label', 'neutral')} "
                        f"(avg score {aggregate.get('average_score', 0):+.2f}, "
                        f"{aggregate.get('bullish_count', 0)} bullish / "
                        f"{aggregate.get('bearish_count', 0)} bearish of "
                        f"{aggregate.get('scored_count', 0)} scored)"
                    )
                headlines = tone.get("headlines") or []
                if headlines:
                    parts.append("- LATEST HEADLINES:")
                    for item in headlines[:10]:
                        label = item.get("sentiment_label") or "?"
                        parts.append(
                            f"  - [{label}] {item.get('title', '')} "
                            f"({item.get('publisher') or 'unknown publisher'})"
                        )

        # ---- Portfolio context (authorized requests only) ----
        if portfolio_ctx := context.get("portfolio_context"):
            if "error" in portfolio_ctx:
                parts.append(
                    "\nPORTFOLIO: not available for this request "
                    f"({portfolio_ctx.get('error')})"
                )
            else:
                parts.append("\nPORTFOLIO (user-supplied records):")
                parts.append(f"- Positions: {portfolio_ctx.get('positions_count', 0)}")
                total_value = portfolio_ctx.get("total_value")
                total_cost = portfolio_ctx.get("total_cost_basis")
                total_pnl = portfolio_ctx.get("total_pnl")
                total_pnl_pct = portfolio_ctx.get("total_pnl_pct")
                if total_cost is not None:
                    parts.append(f"- Cost basis: PKR {total_cost:,.2f}")
                if total_value is not None:
                    parts.append(f"- Market value: PKR {total_value:,.2f}")
                else:
                    parts.append("- Market value: unavailable (live prices missing for some holdings)")
                if total_pnl is not None:
                    pct = f" ({total_pnl_pct:+.2f}%)" if total_pnl_pct is not None else ""
                    parts.append(f"- Unrealised P/L: PKR {total_pnl:,.2f}{pct}")
                holdings = portfolio_ctx.get("holdings") or []
                if holdings:
                    parts.append("\nHOLDINGS:")
                    for holding in holdings[:10]:
                        line = (
                            f"- {holding.get('symbol', '?')}: "
                            f"{holding.get('shares', 0)} shares @ "
                            f"PKR {holding.get('avg_cost', 0):,.2f}"
                        )
                        market_value = holding.get("market_value")
                        if market_value is None:
                            line += " | current price unavailable"
                        else:
                            line += f" = PKR {market_value:,.2f}"
                            if holding.get("pnl") is not None:
                                pnl_pct = holding.get("pnl_pct")
                                pct = f" ({pnl_pct:+.2f}%)" if pnl_pct is not None else ""
                                line += f" | P/L PKR {holding['pnl']:,.2f}{pct}"
                        if holding.get("note"):
                            line += f" | note: {holding['note']}"
                        parts.append(line)

        # ---- News desk context ----
        if news_ctx := context.get("news_context"):
            headlines = news_ctx.get("recent_headlines") or []
            if headlines:
                parts.append(f"\nRECENT HEADLINES ({len(headlines)}):")
                for item in headlines:
                    parts.append(
                        f"- [{item.get('published_at') or 'date unknown'}] "
                        f"{item.get('category') or 'general'}: {item.get('title', '')}"
                    )
            aggregate = news_ctx.get("aggregate_sentiment")
            if aggregate:
                parts.append(
                    "AGGREGATE HEADLINE SENTIMENT: "
                    f"{aggregate.get('label', 'neutral')} "
                    f"(avg score {aggregate.get('average_score', 0):+.2f}, "
                    f"{aggregate.get('bullish_count', 0)} bullish / "
                    f"{aggregate.get('bearish_count', 0)} bearish)"
                )

        # ---- Comparison context (spec Q) ----
        if comparison := context.get("data"):
            if context.get("comparison_type") == "stock_comparison":
                parts.append("\nSTOCK COMPARISON:")
                for symbol_key, entry in comparison.items():
                    if not isinstance(entry, dict):
                        continue
                    if entry.get("error"):
                        parts.append(
                            f"- {symbol_key}: DATA UNAVAILABLE ({entry['error']}) — do not compare this symbol"
                        )
                        continue
                    quote = entry.get("price") or {}
                    line = f"- {symbol_key}:"
                    if quote.get("price") is not None:
                        line += f" price {quote['price']}"
                        if quote.get("change_percent") is not None:
                            line += f" ({quote['change_percent']:+.2f}%)"
                    else:
                        line += " price unavailable"
                    sentiment = entry.get("sentiment")
                    if sentiment:
                        line += f" | sentiment {sentiment.get('label', 'NEUTRAL')}"
                    parts.append(line)
                    for item in (entry.get("recent_news") or [])[:2]:
                        parts.append(f"    news: {item.get('title', '')}")
                parts.append(
                    "Only compare fields present for both symbols; state clearly which fields "
                    "were unavailable."
                )

        return "\n".join(parts) if parts else "No additional context data available."

    # ------------------------------------------------------------------
    # Small formatting helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_quote(source: Dict[str, Any]) -> str:
        """Render a quote block, or '' when the provider returned no price."""
        price = source.get("price", source.get("last"))
        if price is None:
            return "UNAVAILABLE from the data provider"
        bits = [f"{price}"]
        if source.get("previous_close") is not None:
            bits.append(f"previous close {source['previous_close']}")
        if source.get("change_percent") is not None:
            bits.append(f"day change {source['change_percent']:+.2f}%")
        if source.get("last_date"):
            bits.append(f"as of {source['last_date']}")
        return ", ".join(bits)

    @staticmethod
    def _format_sentiment(sentiment: Dict[str, Any]) -> str:
        """Render a sentiment block, tolerating the error/no-data shapes."""
        label = sentiment.get("label", "NEUTRAL")
        score = sentiment.get("score")
        confidence = sentiment.get("confidence")
        origin = sentiment.get("source", "unknown")
        count = sentiment.get("article_count")
        bits = [str(label)]
        if score is not None:
            bits.append(f"score {score:+.2f}")
        if confidence is not None:
            bits.append(f"confidence {confidence:.2f}")
        if count is not None:
            bits.append(f"from {count} items")
        bits.append(f"source: {origin}")
        if sentiment.get("error"):
            bits.append(f"error: {sentiment['error']}")
        return ", ".join(bits)
    
    def build_suggested_prompts(
        self, context: Dict[str, Any]
    ) -> List[str]:
        """
        Generate context-aware suggested prompts based on current page.
        
        Args:
            context: Current context from ContextBuilder
            
        Returns:
            List of suggested prompt strings
        """
        page_type = context.get("page_type", "unknown")
        symbol = context.get("symbol")
        
        if page_type == "stock_detail" and symbol:
            return [
                f"Explain today's price movement for {symbol}",
                f"Analyze the current trend for {symbol}",
                f"Summarize recent news about {symbol}",
                f"What do the latest announcements mean for {symbol}?",
                f"Compare {symbol} with KSE100 performance",
            ]
        
        elif page_type == "index_detail" and symbol:
            return [
                f"Analyze {symbol} performance today",
                f"What's driving {symbol} movement?",
                f"Compare {symbol} with other indices",
                "Which sectors are contributing most?",
            ]
        
        elif page_type == "market_overview":
            return [
                "What's driving today's market?",
                "Which sectors are strongest today?",
                "Summarize today's market tone",
                "What are the top movers?",
                "Analyze market sentiment",
            ]
        
        elif page_type == "portfolio":
            return [
                "Analyze my portfolio performance",
                "Which holding contributes most to my P&L?",
                "Show my largest exposure",
                "Summarize my portfolio concentration",
                "What's my portfolio's sector allocation?",
            ]
        
        elif page_type == "news":
            return [
                "Summarize today's top financial news",
                "What are the major market themes?",
                "Explain the impact of recent PSX news",
                "Which stocks are most mentioned in news?",
            ]
        
        elif page_type == "sentiment":
            return [
                "Explain current market sentiment",
                "Which stocks have the strongest sentiment?",
                "How has sentiment changed recently?",
                "What's driving sentiment shifts?",
            ]

        elif page_type == "watchlist":
            return [
                "Which names on my watchlist moved most today?",
                "Any notable news on my watchlist today?",
                "Which watchlist names look weakest right now?",
                "Summarise sentiment across my watchlist",
            ]

        elif page_type == "announcements":
            return [
                "Summarise the latest PSX announcements",
                "Which announcements look materially price-sensitive?",
                "Any corporate actions announced recently?",
                "What should I watch after these filings?",
            ]

        elif page_type == "screener":
            return [
                "Explain what these screen results mean",
                "Which of these names have the strongest momentum?",
                "Which of these look most extended?",
                "Summarise the common traits in these results",
            ]

        elif page_type == "comparison":
            return [
                "Compare HBL and MEBL",
                "Compare OGDC and PPL",
                "Compare LUCK and ENGRO",
            ]

        elif page_type == "forex_commodities":
            return [
                "What is moving in FX today?",
                "How is PKR behaving against the dollar?",
                "Summarise commodity moves and what they mean for PSX",
            ]

        else:
            return [
                "What's happening in the market today?",
                "Show me top gainers and losers",
                "Analyze KSE100 performance",
                "What should I know about PSX today?",
            ]


def create_comparison_prompt(
    symbols: List[str],
    comparison_context: Dict[str, Any],
) -> List[Dict[str, str]]:
    """
    Create a specialized prompt for stock comparison.
    
    Args:
        symbols: List of symbols to compare
        comparison_context: Context from build_comparison_context
        
    Returns:
        Message list for AI provider
    """
    builder = PromptBuilder()
    
    # Build a focused comparison question
    question = (
        f"Compare {' and '.join(symbols)}. "
        f"Analyze their relative performance, sentiment, and recent news. "
        f"Highlight key differences and similarities."
    )
    
    return builder.build_messages(
        user_question=question,
        context=comparison_context,
    )
