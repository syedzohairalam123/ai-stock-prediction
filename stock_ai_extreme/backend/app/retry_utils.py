"""
Retry utilities with exponential backoff using tenacity.
Provides decorators for retrying failed operations with configurable strategies.
"""
from functools import wraps
from typing import Callable, Type, Tuple, Any
import tenacity
from .logging_config import get_logger

logger = get_logger("neural_market.retry")

def retry_on_exception(
    exception_types: Type[Exception] | Tuple[Type[Exception], ...] = Exception,
    max_attempts: int = 3,
    wait_exponential_multiplier: int = 1000,
    wait_exponential_max: int = 10000,
    stop_after_delay: int = 60,
) -> Callable:
    """
    Decorator to retry a function on specific exceptions with exponential backoff.
    
    Args:
        exception_types: Exception type(s) to catch and retry on
        max_attempts: Maximum number of retry attempts
        wait_exponential_multiplier: Base multiplier for exponential backoff (ms)
        wait_exponential_max: Maximum wait time between retries (ms)
        stop_after_delay: Maximum total time to spend retrying (seconds)
    
    Returns:
        Decorated function with retry logic
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            retryer = tenacity.AsyncRetrying(
                stop=tenacity.stop_after_attempt(max_attempts) | tenacity.stop_after_delay(stop_after_delay),
                wait=tenacity.wait_exponential(multiplier=wait_exponential_multiplier, max=wait_exponential_max),
                retry=tenacity.retry_if_exception_type(exception_types),
                before_sleep=tenacity.before_sleep_log(logger, "WARNING"),
                reraise=True,
            )
            return await retryer.call(func, *args, **kwargs)
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            retryer = tenacity.Retrying(
                stop=tenacity.stop_after_attempt(max_attempts) | tenacity.stop_after_delay(stop_after_delay),
                wait=tenacity.wait_exponential(multiplier=wait_exponential_multiplier, max=wait_exponential_max),
                retry=tenacity.retry_if_exception_type(exception_types),
                before_sleep=tenacity.before_sleep_log(logger, "WARNING"),
                reraise=True,
            )
            return retryer.call(func, *args, **kwargs)
        
        import inspect
        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator

def retry_on_network_error(max_attempts: int = 3) -> Callable:
    """
    Specialized retry decorator for network-related errors.
    Retries on connection errors, timeouts, and HTTP errors.
    
    Args:
        max_attempts: Maximum number of retry attempts
    
    Returns:
        Decorated function with network retry logic
    """
    network_exceptions = (
        ConnectionError,
        TimeoutError,
        OSError,
    )
    
    return retry_on_exception(
        exception_types=network_exceptions,
        max_attempts=max_attempts,
        wait_exponential_multiplier=1000,
        wait_exponential_max=30000,
        stop_after_delay=120,
    )

def retry_on_provider_error(max_attempts: int = 2) -> Callable:
    """
    Specialized retry decorator for data provider errors.
    More conservative retry strategy for external API calls.
    
    Args:
        max_attempts: Maximum number of retry attempts
    
    Returns:
        Decorated function with provider retry logic
    """
    return retry_on_exception(
        exception_types=Exception,
        max_attempts=max_attempts,
        wait_exponential_multiplier=2000,
        wait_exponential_max=10000,
        stop_after_delay=30,
    )