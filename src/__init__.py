"""
Ralph-Py: Python implementation of Ralph orchestrator for Claude Code CLI.

This package provides a Python interface to run and orchestrate Claude Code CLI,
similar to the Rust-based ralph-orchestrator.
"""

__version__ = "0.1.0"

from stream_parser import (
    AssistantMessage,
    ClaudeStreamEvent,
    ClaudeStreamParser,
    ContentBlock,
    SessionResult,
    Usage,
    UserContentBlock,
)
from executor import (
    ClaudeExecutor,
    ExecutorConfig,
    ExecutionResult,
    TerminationType,
    OutputFormat,
)

__all__ = [
    # Stream Parser
    "ClaudeStreamParser",
    "ClaudeStreamEvent",
    "AssistantMessage",
    "ContentBlock",
    "UserContentBlock",
    "Usage",
    "SessionResult",
    # Executor
    "ClaudeExecutor",
    "ExecutorConfig",
    "ExecutionResult",
    "TerminationType",
    "OutputFormat",
]
