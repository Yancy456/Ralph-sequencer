"""
Logging system for ralph-sq.

Provides console and file logging with rich formatting.
"""

import io
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.logging import RichHandler

# Constants
OUTPUT_DIR = Path(".ralph_debug")

# Console for rich output
console = Console()

# Global variables to store the current run context
_current_run_dir: Optional[Path] = None
_current_run_id: Optional[str] = None

# Logger instances
_logger = None  # Will be set in setup_logging
_file_logger = None  # File-only logger for log_print


def get_run_dir() -> Path:
    """Get or create the current run directory."""
    global _current_run_dir
    if _current_run_dir is None:
        OUTPUT_DIR.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        _current_run_dir = OUTPUT_DIR / timestamp
        _current_run_dir.mkdir(exist_ok=True)
    return _current_run_dir


def get_log_path() -> Path:
    """Generate log file path in the current run directory."""
    run_dir = get_run_dir()
    if _current_run_id:
        return run_dir / f"{_current_run_id}.log"
    return run_dir / "run.log"


def _sanitize_run_id(run_id: str) -> str:
    """Sanitize run id for filesystem usage."""
    safe_id = run_id.strip()
    if os.sep:
        safe_id = safe_id.replace(os.sep, "_")
    if os.altsep:
        safe_id = safe_id.replace(os.altsep, "_")
    return safe_id


def set_run_id(run_id: str) -> None:
    """Initialize the run id."""
    global _current_run_id
    safe_id = _sanitize_run_id(run_id)
    _current_run_id = safe_id


def get_run_id() -> Optional[str]:
    """Get the current run ID."""
    return _current_run_id


def log_print(*args, **kwargs) -> None:
    """Print to console and also log to file."""
    # Print to console first
    console.print(*args, **kwargs)
    
    # Also log to file (strip Rich markup for plain text logging)
    # Use file_logger to avoid duplicate console output from RichHandler
    if _file_logger:
        # Use a StringIO buffer to capture plain text output
        buffer = io.StringIO()
        temp_console = Console(file=buffer, force_terminal=False, legacy_windows=False)
        temp_console.print(*args, **kwargs)
        plain_text = buffer.getvalue()
        buffer.close()
        
        # Remove extra whitespace but preserve line breaks
        lines = [line.strip() for line in plain_text.split('\n') if line.strip()]
        for line in lines:
            if line:
                _file_logger.info(line)


def log_print_exception() -> None:
    """Print exception to console and also log to file."""
    console.print_exception()
    if _logger:
        import traceback
        _logger.exception("Exception occurred")


def setup_logging() -> None:
    """Set up logging with rich handler and file handler."""
    level = logging.INFO
    log_path = get_log_path()
    
    # Create handlers
    handlers = [
        RichHandler(
            console=console, 
            rich_tracebacks=False, 
            show_time=False, 
            show_level=False,
        ),
        logging.FileHandler(log_path, encoding='utf-8'),
    ]
    
    # File handler format with timestamp
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    handlers[1].setFormatter(file_formatter)
    
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=handlers,
    )
    
    global _logger, _file_logger
    _logger = logging.getLogger(__name__)
    
    # Create a file-only logger for log_print to avoid duplicate console output
    _file_logger = logging.getLogger(f"{__name__}.file_only")
    _file_logger.setLevel(level)
    # Remove all handlers to avoid console output
    _file_logger.handlers = []
    # Add only file handler
    file_handler = logging.FileHandler(log_path, encoding='utf-8')
    file_handler.setFormatter(file_formatter)
    _file_logger.addHandler(file_handler)
    _file_logger.propagate = False  # Don't propagate to root logger
    
    # Log file path only to file, not to console to avoid showing file paths
    _file_logger.info(f"Log file: {log_path}")
