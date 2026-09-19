"""
AI Provider Abstraction Layer

Provides a unified interface for multiple AI providers (OpenAI, OpenRouter, Anthropic).
Never exposes API keys to the client. All AI communication happens server-side.
"""
from abc import ABC, abstractmethod
from typing import AsyncIterator, Dict, List, Optional
import httpx
import structlog
from openai import AsyncOpenAI
from ..config import settings

logger = structlog.get_logger(__name__)


class AIProvider(ABC):
    """Base class for AI providers. All providers must implement these methods."""
    
    @abstractmethod
    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> Dict:
        """
        Get a non-streaming chat completion.
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            temperature: Sampling temperature (0-1)
            max_tokens: Maximum tokens in response
            
        Returns:
            Dict with 'content', 'model', 'usage' keys
        """
        pass
    
    @abstractmethod
    async def chat_completion_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[str]:
        """
        Get a streaming chat completion.
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            temperature: Sampling temperature (0-1)
            max_tokens: Maximum tokens in response
            
        Yields:
            Content chunks as they arrive
        """
        pass
    
    @abstractmethod
    def get_model_name(self) -> str:
        """Return the model name for this provider."""
        pass


class OpenAIProvider(AIProvider):
    """OpenAI provider using official SDK."""
    
    def __init__(self):
        if not settings.openai_api_key:
            raise ValueError("OpenAI API key not configured")
        
        self.client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            timeout=settings.openai_timeout_seconds,
        )
        self.model = settings.openai_model
        self.max_tokens = settings.openai_max_tokens
        logger.info("openai_provider_initialized", model=self.model)
    
    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> Dict:
        """Get non-streaming OpenAI completion."""
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens or self.max_tokens,
            )
            
            return {
                "content": response.choices[0].message.content,
                "model": response.model,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                },
                "finish_reason": response.choices[0].finish_reason,
            }
        except Exception as e:
            logger.error("openai_completion_error", error=str(e))
            raise
    
    async def chat_completion_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[str]:
        """Get streaming OpenAI completion."""
        try:
            stream = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens or self.max_tokens,
                stream=True,
            )
            
            async for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            logger.error("openai_stream_error", error=str(e))
            raise
    
    def get_model_name(self) -> str:
        return self.model


class OpenRouterProvider(AIProvider):
    """OpenRouter provider for access to multiple models through one API."""
    
    def __init__(self):
        if not settings.openrouter_api_key:
            raise ValueError("OpenRouter API key not configured")
        
        # OpenRouter uses OpenAI-compatible API
        self.client = AsyncOpenAI(
            base_url=settings.openrouter_url,
            api_key=settings.openrouter_api_key,
            timeout=settings.openrouter_timeout_seconds,
        )
        self.model = settings.openrouter_model
        logger.info("openrouter_provider_initialized", model=self.model)
    
    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> Dict:
        """Get non-streaming OpenRouter completion."""
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens or 4000,
            )
            
            return {
                "content": response.choices[0].message.content,
                "model": response.model,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                    "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                    "total_tokens": response.usage.total_tokens if response.usage else 0,
                },
                "finish_reason": response.choices[0].finish_reason,
            }
        except Exception as e:
            logger.error("openrouter_completion_error", error=str(e))
            raise
    
    async def chat_completion_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[str]:
        """Get streaming OpenRouter completion."""
        try:
            stream = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens or 4000,
                stream=True,
            )
            
            async for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            logger.error("openrouter_stream_error", error=str(e))
            raise
    
    def get_model_name(self) -> str:
        return self.model


class AnthropicProvider(AIProvider):
    """Anthropic Claude provider (direct API, not via OpenRouter)."""
    
    def __init__(self):
        if not settings.anthropic_api_key:
            raise ValueError("Anthropic API key not configured")
        
        self.api_key = settings.anthropic_api_key
        self.model = settings.anthropic_model
        self.base_url = "https://api.anthropic.com/v1"
        self.timeout = settings.anthropic_timeout_seconds
        logger.info("anthropic_provider_initialized", model=self.model)
    
    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> Dict:
        """Get non-streaming Anthropic completion."""
        try:
            # Convert messages to Anthropic format
            system_message = None
            anthropic_messages = []
            
            for msg in messages:
                if msg["role"] == "system":
                    system_message = msg["content"]
                else:
                    anthropic_messages.append({
                        "role": msg["role"],
                        "content": msg["content"],
                    })
            
            payload = {
                "model": self.model,
                "messages": anthropic_messages,
                "max_tokens": max_tokens or 4000,
                "temperature": temperature,
            }
            
            if system_message:
                payload["system"] = system_message
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/messages",
                    headers={
                        "x-api-key": self.api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
            
            return {
                "content": data["content"][0]["text"],
                "model": data["model"],
                "usage": {
                    "prompt_tokens": data["usage"]["input_tokens"],
                    "completion_tokens": data["usage"]["output_tokens"],
                    "total_tokens": data["usage"]["input_tokens"] + data["usage"]["output_tokens"],
                },
                "finish_reason": data.get("stop_reason", "stop"),
            }
        except Exception as e:
            logger.error("anthropic_completion_error", error=str(e))
            raise
    
    async def chat_completion_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[str]:
        """Get streaming Anthropic completion."""
        try:
            # Convert messages to Anthropic format
            system_message = None
            anthropic_messages = []
            
            for msg in messages:
                if msg["role"] == "system":
                    system_message = msg["content"]
                else:
                    anthropic_messages.append({
                        "role": msg["role"],
                        "content": msg["content"],
                    })
            
            payload = {
                "model": self.model,
                "messages": anthropic_messages,
                "max_tokens": max_tokens or 4000,
                "temperature": temperature,
                "stream": True,
            }
            
            if system_message:
                payload["system"] = system_message
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/messages",
                    headers={
                        "x-api-key": self.api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json=payload,
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            try:
                                import json
                                data = json.loads(line[6:])
                                if data.get("type") == "content_block_delta":
                                    if delta_text := data.get("delta", {}).get("text"):
                                        yield delta_text
                            except json.JSONDecodeError:
                                continue
        except Exception as e:
            logger.error("anthropic_stream_error", error=str(e))
            raise
    
    def get_model_name(self) -> str:
        return self.model


def get_ai_provider() -> AIProvider:
    """
    Factory function to get the configured AI provider.
    
    Returns:
        Configured AIProvider instance
        
    Raises:
        ValueError: If provider not configured or invalid provider type
    """
    provider_name = settings.ai_provider.lower()
    
    try:
        if provider_name == "openai":
            return OpenAIProvider()
        elif provider_name == "openrouter":
            return OpenRouterProvider()
        elif provider_name == "anthropic":
            return AnthropicProvider()
        else:
            raise ValueError(f"Unknown AI provider: {provider_name}")
    except Exception as e:
        logger.error("ai_provider_initialization_error", provider=provider_name, error=str(e))
        raise
