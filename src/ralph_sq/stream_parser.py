"""
Claude stream event types for parsing `--output-format stream-json` output.

When invoked with `--output-format stream-json`, Claude emits newline-delimited
JSON events. This module provides typed Python structures for deserializing
and processing these events.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional, Union

logger = logging.getLogger(__name__)


@dataclass
class Usage:
    """Token usage statistics."""
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class TextContent:
    """Plain text output from Claude."""
    type: str = "text"
    text: str = ""


@dataclass
class ToolUseContent:
    """Tool invocation by Claude."""
    type: str = "tool_use"
    id: str = ""
    name: str = ""
    input: dict[str, Any] = field(default_factory=dict)


ContentBlock = Union[TextContent, ToolUseContent]


@dataclass
class ToolResultContent:
    """Result from a tool invocation."""
    type: str = "tool_result"
    tool_use_id: str = ""
    content: str = ""


UserContentBlock = ToolResultContent


@dataclass
class AssistantMessage:
    """Message content from Claude's assistant responses."""
    content: list[ContentBlock] = field(default_factory=list)


@dataclass
class UserMessage:
    """Message content from tool results (user turn)."""
    content: list[UserContentBlock] = field(default_factory=list)


@dataclass
class SessionResult:
    """Session complete - final event with stats."""
    duration_ms: int = 0
    total_cost_usd: float = 0.0
    num_turns: int = 0
    is_error: bool = False


@dataclass
class SystemEvent:
    """Session initialization - first event emitted."""
    type: str = "system"
    session_id: str = ""
    model: str = ""
    tools: list[Any] = field(default_factory=list)
    parent_tool_use_id: Optional[str] = None


@dataclass
class AssistantEvent:
    """Claude's response - contains text or tool invocations."""
    type: str = "assistant"
    message: AssistantMessage = field(default_factory=AssistantMessage)
    usage: Optional[Usage] = None
    parent_tool_use_id: Optional[str] = None


@dataclass
class UserEvent:
    """Tool results returned to Claude."""
    type: str = "user"
    message: UserMessage = field(default_factory=UserMessage)
    parent_tool_use_id: Optional[str] = None


@dataclass
class ResultEvent:
    """Session complete - final event with stats."""
    type: str = "result"
    duration_ms: int = 0
    total_cost_usd: float = 0.0
    num_turns: int = 0
    is_error: bool = False
    parent_tool_use_id: Optional[str] = None


ClaudeStreamEvent = Union[SystemEvent, AssistantEvent, UserEvent, ResultEvent]


class ClaudeStreamParser:
    """Parses NDJSON lines from Claude's stream output."""
    
    @staticmethod
    def parse_line(line: str) -> Optional[ClaudeStreamEvent]:
        """
        Parse a single line of NDJSON output.
        
        Returns None for empty lines or malformed JSON.
        """
        trimmed = line.strip()
        if not trimmed:
            return None
        
        try:
            data = json.loads(trimmed)
        except json.JSONDecodeError as e:
            logger.debug(f"Skipping malformed JSON line: {_truncate(trimmed, 100)} (error: {e})")
            return None
        
        event_type = data.get("type")
        parent_tool_use_id = data.get("parent_tool_use_id")
        
        if event_type == "system":
            return SystemEvent(
                type="system",
                session_id=data.get("session_id", ""),
                model=data.get("model", ""),
                tools=data.get("tools", []),
                parent_tool_use_id=parent_tool_use_id,
            )
        
        elif event_type == "assistant":
            message_data = data.get("message", {})
            content_blocks = []
            
            for block in message_data.get("content", []):
                block_type = block.get("type")
                if block_type == "text":
                    content_blocks.append(TextContent(
                        type="text",
                        text=block.get("text", ""),
                    ))
                elif block_type == "tool_use":
                    content_blocks.append(ToolUseContent(
                        type="tool_use",
                        id=block.get("id", ""),
                        name=block.get("name", ""),
                        input=block.get("input", {}),
                    ))
            
            usage_data = data.get("usage")
            usage = None
            if usage_data:
                usage = Usage(
                    input_tokens=usage_data.get("input_tokens", 0),
                    output_tokens=usage_data.get("output_tokens", 0),
                )
            
            return AssistantEvent(
                type="assistant",
                message=AssistantMessage(content=content_blocks),
                usage=usage,
                parent_tool_use_id=parent_tool_use_id,
            )
        
        elif event_type == "user":
            message_data = data.get("message", {})
            content_blocks = []
            
            for block in message_data.get("content", []):
                if block.get("type") == "tool_result":
                    content_blocks.append(ToolResultContent(
                        type="tool_result",
                        tool_use_id=block.get("tool_use_id", ""),
                        content=block.get("content", ""),
                    ))
            
            return UserEvent(
                type="user",
                message=UserMessage(content=content_blocks),
                parent_tool_use_id=parent_tool_use_id,
            )
        
        elif event_type == "result":
            return ResultEvent(
                type="result",
                duration_ms=data.get("duration_ms", 0),
                total_cost_usd=data.get("total_cost_usd", 0.0),
                num_turns=data.get("num_turns", 0),
                is_error=data.get("is_error", False),
                parent_tool_use_id=parent_tool_use_id,
            )
        
        # Unknown event type
        logger.debug(f"Unknown event type: {event_type}")
        return None
    
    @staticmethod
    def extract_text(event: ClaudeStreamEvent) -> str:
        """Extract text content from an event."""
        if isinstance(event, AssistantEvent):
            texts = []
            for block in event.message.content:
                if isinstance(block, TextContent):
                    texts.append(block.text)
            return "\n".join(texts)
        return ""
    
    @staticmethod
    def get_tool_calls(event: ClaudeStreamEvent) -> list[ToolUseContent]:
        """Extract tool calls from an event."""
        if isinstance(event, AssistantEvent):
            return [
                block for block in event.message.content
                if isinstance(block, ToolUseContent)
            ]
        return []


def _truncate(s: str, max_len: int) -> str:
    """Truncates a string to a maximum length, adding '...' if truncated."""
    if len(s) <= max_len:
        return s
    return s[:max_len] + "..."
