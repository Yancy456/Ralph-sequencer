"""
Ralph-Py: Python implementation of Ralph orchestrator for Claude Code CLI.

This package provides a Python interface to run and orchestrate Claude Code CLI,
similar to the Rust-based ralph-orchestrator.
"""

__version__ = "0.1.0"

from ralph_py.claude_backend import ClaudeBackend, OutputFormat, PromptMode
from ralph_py.stream_parser import (
    AssistantMessage,
    ClaudeStreamEvent,
    ClaudeStreamParser,
    ContentBlock,
    SessionResult,
    Usage,
    UserContentBlock,
)
from ralph_py.executor import (
    ClaudeExecutor,
    ExecutorConfig,
    ExecutionResult,
    TerminationType,
)

__all__ = [
    # Backend
    "ClaudeBackend",
    "OutputFormat",
    "PromptMode",
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
]
