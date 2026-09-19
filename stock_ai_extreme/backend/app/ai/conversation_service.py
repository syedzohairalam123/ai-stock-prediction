"""
Conversation Service

Manages conversation history, context windows, and message storage.
Handles conversation CRUD operations and context window management to prevent
token overflow.
"""
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import structlog
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Conversation, Message
from ..config import settings

logger = structlog.get_logger(__name__)


class ConversationService:
    """
    Service for managing AI assistant conversations.
    
    Responsibilities:
    - Create/read/update/delete conversations
    - Manage message history
    - Context window management
    - Auto-generate conversation titles
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.max_messages = settings.ai_max_conversation_messages
    
    async def create_conversation(
        self,
        title: Optional[str] = None,
        context_snapshot: Optional[Dict] = None,
        user_id: Optional[str] = None,
    ) -> Conversation:
        """
        Create a new conversation.
        
        Args:
            title: Optional conversation title (auto-generated if not provided)
            context_snapshot: Context at conversation start
            user_id: Optional user identifier
            
        Returns:
            Created Conversation object
        """
        try:
            conversation = Conversation(
                user_id=user_id,
                title=title or self._generate_default_title(),
                context_snapshot=context_snapshot or {},
            )
            
            self.db.add(conversation)
            await self.db.commit()
            await self.db.refresh(conversation)
            
            logger.info(
                "conversation_created",
                conversation_id=conversation.id,
                title=conversation.title,
            )
            
            return conversation
            
        except Exception as e:
            logger.error("conversation_create_error", error=str(e))
            await self.db.rollback()
            raise
    
    async def get_conversation(self, conversation_id: int) -> Optional[Conversation]:
        """Get conversation by ID."""
        try:
            query = select(Conversation).where(Conversation.id == conversation_id)
            result = await self.db.execute(query)
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error("conversation_get_error", error=str(e), conversation_id=conversation_id)
            return None
    
    async def list_conversations(
        self,
        user_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[Conversation], int]:
        """
        List conversations with pagination.
        
        Args:
            user_id: Optional user filter
            limit: Maximum conversations to return
            offset: Pagination offset
            
        Returns:
            Tuple of (conversations list, total count)
        """
        try:
            # Build query
            query = select(Conversation)
            count_query = select(func.count(Conversation.id))
            
            if user_id:
                query = query.where(Conversation.user_id == user_id)
                count_query = count_query.where(Conversation.user_id == user_id)
            
            # Order by most recent
            query = query.order_by(desc(Conversation.updated_at))
            
            # Apply pagination
            query = query.limit(limit).offset(offset)
            
            # Execute queries
            result = await self.db.execute(query)
            conversations = result.scalars().all()
            
            count_result = await self.db.execute(count_query)
            total = count_result.scalar()
            
            return list(conversations), total
            
        except Exception as e:
            logger.error("conversations_list_error", error=str(e))
            return [], 0
    
    async def update_conversation_title(
        self, conversation_id: int, new_title: str
    ) -> bool:
        """Update conversation title."""
        try:
            conversation = await self.get_conversation(conversation_id)
            if not conversation:
                return False
            
            conversation.title = new_title
            await self.db.commit()
            
            logger.info(
                "conversation_title_updated",
                conversation_id=conversation_id,
                new_title=new_title,
            )
            
            return True
            
        except Exception as e:
            logger.error(
                "conversation_title_update_error",
                error=str(e),
                conversation_id=conversation_id,
            )
            await self.db.rollback()
            return False
    
    async def delete_conversation(self, conversation_id: int) -> bool:
        """Delete conversation and all its messages."""
        try:
            # Delete messages first
            await self.db.execute(
                Message.__table__.delete().where(
                    Message.conversation_id == conversation_id
                )
            )
            
            # Delete conversation
            await self.db.execute(
                Conversation.__table__.delete().where(
                    Conversation.id == conversation_id
                )
            )
            
            await self.db.commit()
            
            logger.info("conversation_deleted", conversation_id=conversation_id)
            
            return True
            
        except Exception as e:
            logger.error(
                "conversation_delete_error",
                error=str(e),
                conversation_id=conversation_id,
            )
            await self.db.rollback()
            return False
    
    async def add_message(
        self,
        conversation_id: int,
        role: str,
        content: str,
        context_used: Optional[Dict] = None,
        citations: Optional[List] = None,
        token_usage: Optional[Dict] = None,
        model: Optional[str] = None,
        processing_time_ms: Optional[int] = None,
    ) -> Message:
        """
        Add a message to a conversation.
        
        Args:
            conversation_id: Conversation ID
            role: Message role (user, assistant, system)
            content: Message content
            context_used: Context sent with this message
            citations: Source citations
            token_usage: Token usage stats
            model: Model that generated the message
            processing_time_ms: Processing time in milliseconds
            
        Returns:
            Created Message object
        """
        try:
            message = Message(
                conversation_id=conversation_id,
                role=role,
                content=content,
                context_used=context_used or {},
                citations=citations or [],
                token_usage=token_usage,
                model=model,
                processing_time_ms=processing_time_ms,
            )
            
            self.db.add(message)
            
            # Update conversation's updated_at timestamp
            conversation = await self.get_conversation(conversation_id)
            if conversation:
                conversation.updated_at = datetime.utcnow()
            
            await self.db.commit()
            await self.db.refresh(message)
            
            logger.info(
                "message_added",
                conversation_id=conversation_id,
                role=role,
                message_id=message.id,
            )
            
            return message
            
        except Exception as e:
            logger.error(
                "message_add_error",
                error=str(e),
                conversation_id=conversation_id,
            )
            await self.db.rollback()
            raise
    
    async def get_conversation_messages(
        self, conversation_id: int, limit: Optional[int] = None
    ) -> List[Message]:
        """
        Get messages for a conversation.
        
        Args:
            conversation_id: Conversation ID
            limit: Optional limit (for context window management)
            
        Returns:
            List of Message objects, ordered by created_at
        """
        try:
            query = (
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at)
            )
            
            if limit:
                query = query.limit(limit)
            
            result = await self.db.execute(query)
            return list(result.scalars().all())
            
        except Exception as e:
            logger.error(
                "messages_get_error",
                error=str(e),
                conversation_id=conversation_id,
            )
            return []
    
    async def get_recent_messages_for_context(
        self, conversation_id: int, max_messages: Optional[int] = None
    ) -> List[Dict[str, str]]:
        """
        Get recent messages formatted for AI context.
        
        Implements context window management to prevent token overflow.
        
        Args:
            conversation_id: Conversation ID
            max_messages: Maximum messages to return (defaults to config setting)
            
        Returns:
            List of message dicts with 'role' and 'content' keys
        """
        try:
            limit = max_messages or self.max_messages
            
            # Get recent messages
            messages = await self.get_conversation_messages(
                conversation_id=conversation_id,
                limit=limit,
            )
            
            # Format for AI provider
            formatted_messages = []
            for msg in messages:
                if msg.role in ["user", "assistant"]:  # Skip system messages
                    formatted_messages.append({
                        "role": msg.role,
                        "content": msg.content,
                    })
            
            return formatted_messages
            
        except Exception as e:
            logger.error(
                "context_messages_get_error",
                error=str(e),
                conversation_id=conversation_id,
            )
            return []
    
    async def auto_generate_title(
        self, conversation_id: int, first_message: str
    ) -> bool:
        """
        Auto-generate conversation title from first user message.
        
        Args:
            conversation_id: Conversation ID
            first_message: First user message
            
        Returns:
            Success boolean
        """
        try:
            # Generate title from first message (simple version)
            # A more advanced version could use AI to generate a better title
            title = first_message[:50].strip()
            if len(first_message) > 50:
                title += "..."
            
            return await self.update_conversation_title(conversation_id, title)
            
        except Exception as e:
            logger.error(
                "auto_title_generation_error",
                error=str(e),
                conversation_id=conversation_id,
            )
            return False
    
    def _generate_default_title(self) -> str:
        """Generate default conversation title."""
        return f"Conversation {datetime.utcnow().strftime('%b %d, %Y %H:%M')}"
    
    async def get_conversation_stats(self, conversation_id: int) -> Dict:
        """
        Get statistics for a conversation.
        
        Returns:
            Dict with message count, total tokens, etc.
        """
        try:
            messages = await self.get_conversation_messages(conversation_id)
            
            total_tokens = 0
            user_messages = 0
            assistant_messages = 0
            
            for msg in messages:
                if msg.token_usage:
                    total_tokens += msg.token_usage.get("total_tokens", 0)
                
                if msg.role == "user":
                    user_messages += 1
                elif msg.role == "assistant":
                    assistant_messages += 1
            
            return {
                "total_messages": len(messages),
                "user_messages": user_messages,
                "assistant_messages": assistant_messages,
                "total_tokens": total_tokens,
            }
            
        except Exception as e:
            logger.error(
                "conversation_stats_error",
                error=str(e),
                conversation_id=conversation_id,
            )
            return {}


async def clean_old_conversations(
    db: AsyncSession, days_old: int = 90, user_id: Optional[str] = None
) -> int:
    """
    Clean up old conversations.
    
    Args:
        db: Database session
        days_old: Delete conversations older than this many days
        user_id: Optional user filter
        
    Returns:
        Number of conversations deleted
    """
    try:
        from datetime import timedelta
        
        cutoff_date = datetime.utcnow() - timedelta(days=days_old)
        
        # Find old conversations
        query = select(Conversation).where(Conversation.updated_at < cutoff_date)
        
        if user_id:
            query = query.where(Conversation.user_id == user_id)
        
        result = await db.execute(query)
        old_conversations = result.scalars().all()
        
        # Delete each conversation and its messages
        service = ConversationService(db)
        deleted_count = 0
        
        for conv in old_conversations:
            if await service.delete_conversation(conv.id):
                deleted_count += 1
        
        logger.info(
            "old_conversations_cleaned",
            deleted_count=deleted_count,
            days_old=days_old,
        )
        
        return deleted_count
        
    except Exception as e:
        logger.error("conversation_cleanup_error", error=str(e))
        return 0
