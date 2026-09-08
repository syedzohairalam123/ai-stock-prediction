"""
Professional logging configuration for Neural Market API.
Uses structlog for structured logging with proper formatting and context.
"""
import logging
import sys
from typing import Any
import structlog
from colorama import Fore, Style
from functools import wraps

def configure_logging(log_level: str = "INFO") -> None:
    """
    Configure structured logging for the application.
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    # Configure standard logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper(), logging.INFO),
    )
    
    # Configure structlog
    structlog.configure(
        processors=[
            # Add log level
            structlog.stdlib.add_log_level,
            # Add logger name
            structlog.stdlib.add_logger_name,
            # Add timestamp
            structlog.processors.TimeStamper(fmt="iso"),
            # Handle exceptions
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            # Add call parameters
            structlog.processors.CallsiteParameterAdder(
                [
                    structlog.processors.CallsiteParameter.FILENAME,
                    structlog.processors.CallsiteParameter.FUNC_NAME,
                    structlog.processors.CallsiteParameter.LINENO,
                ]
            ),
            # Development processor for pretty console output
            _dev_processor if log_level.upper() == "DEBUG" else structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

def _dev_processor(logger: Any, method_name: str, event_dict: dict) -> dict:
    """
    Custom processor for development-friendly console output with colors.
    """
    # Color coding by log level
    level = event_dict.get("level", "INFO").upper()
    level_colors = {
        "DEBUG": Fore.CYAN,
        "INFO": Fore.GREEN,
        "WARNING": Fore.YELLOW,
        "ERROR": Fore.RED,
        "CRITICAL": Fore.RED + Style.BRIGHT,
    }
    
    color = level_colors.get(level, Fore.WHITE)
    timestamp = event_dict.get("timestamp", "")
    logger_name = event_dict.get("logger", "")
    module = event_dict.get("filename", "")
    function = event_dict.get("func_name", "")
    line = event_dict.get("lineno", "")
    
    # Format: [TIMESTAMP] [LEVEL] [LOGGER] file:function:line - message
    header = f"{color}[{timestamp}][{level}][{logger_name}]{Style.RESET_ALL}"
    location = f"{Fore.BLUE}{module}:{function}:{line}{Style.RESET_ALL}" if module else ""
    message = event_dict.get("event", "")
    
    # Add extra context if present
    extra_context = " ".join(
        f"{Fore.MAGENTA}{k}={v}{Style.RESET_ALL}" 
        for k, v in event_dict.items() 
        if k not in ["timestamp", "level", "logger", "filename", "func_name", "lineno", "event", "exc_info"]
    )
    
    parts = [header]
    if location:
        parts.append(location)
    if extra_context:
        parts.append(extra_context)
    parts.append(f"{Fore.WHITE}{message}{Style.RESET_ALL}")
    
    event_dict["event"] = " ".join(str(p) for p in parts)
    return event_dict

def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """
    Get a structured logger instance.
    
    Args:
        name: Logger name (usually __name__)
    
    Returns:
        Structured logger instance
    """
    return structlog.get_logger(name)

def log_execution_time(logger: structlog.stdlib.BoundLogger):
    """
    Decorator to log function execution time.
    
    Args:
        logger: Structured logger instance
    """
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            import time
            start_time = time.time()
            try:
                result = await func(*args, **kwargs)
                execution_time = time.time() - start_time
                logger.info(
                    "Function executed successfully",
                    function=func.__name__,
                    execution_time_seconds=round(execution_time, 3),
                )
                return result
            except Exception as e:
                execution_time = time.time() - start_time
                logger.error(
                    "Function execution failed",
                    function=func.__name__,
                    execution_time_seconds=round(execution_time, 3),
                    error=str(e),
                )
                raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            import time
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                execution_time = time.time() - start_time
                logger.info(
                    "Function executed successfully",
                    function=func.__name__,
                    execution_time_seconds=round(execution_time, 3),
                )
                return result
            except Exception as e:
                execution_time = time.time() - start_time
                logger.error(
                    "Function execution failed",
                    function=func.__name__,
                    execution_time_seconds=round(execution_time, 3),
                    error=str(e),
                )
                raise
        
        import inspect
        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    return decorator