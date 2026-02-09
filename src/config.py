"""
Configuration parser for ralph.yaml.

This module provides functionality to load and parse the ralph.yaml
configuration file, which defines roles and repeat sequences.

It uses pydantic to define a strict schema for the YAML structure:
any unexpected / unknown fields will cause validation to fail.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError


# ------------------------------
# Pydantic schema (strict YAML)
# ------------------------------


class _RoleDefModel(BaseModel):
    """Schema for items in top-level `roles` list."""

    role: str
    prompt_file: Optional[str] = None

    model_config = ConfigDict(extra="forbid")


class _SequenceStepModel(BaseModel):
    """Schema for a single step inside a repeat sequence.

    Note: `prompt_file` is allowed here for backward compatibility, but it is
    only used to infer role prompt files (it is not part of `SequenceStep` dataclass).
    """

    role: str
    prompt: Optional[str] = None
    prompt_file: Optional[str] = None
    new_session: bool = True
    interactive: bool = False
    # In interactive mode, max conversation rounds (None = no limit); when exceeded, proceed to next sequence
    max_conversation: Optional[int] = None
    # When set, after N times of "ralph-sq send system:subtask_completed" trigger continue (None = no limit)
    continue_when_subtask: Optional[int] = None

    model_config = ConfigDict(extra="forbid")


class _RepeatSequenceModel(BaseModel):
    """Schema for a repeat sequence entry."""

    sequence: list[_SequenceStepModel]
    repeat: int = 1

    model_config = ConfigDict(extra="forbid")


class _RalphConfigModel(BaseModel):
    """Top-level YAML schema."""

    description: Optional[str] = None
    interactive: bool = False
    language: Optional[str] = None
    roles: Optional[list[_RoleDefModel]] = None
    repeat_sequence: Optional[list[_RepeatSequenceModel]] = None

    model_config = ConfigDict(extra="forbid")


# ------------------------------
# Public dataclasses / API
# ------------------------------


@dataclass
class Role:
    """A role definition with its prompt file."""

    name: str
    prompt_file: Optional[str] = None


@dataclass
class SequenceStep:
    """A single step in a sequence."""

    role: str
    prompt: Optional[str] = None
    new_session: bool = False
    interactive: bool = False
    # In interactive mode, max conversation rounds (None = no limit); when exceeded, proceed to next sequence
    max_conversation: Optional[int] = None
    # When set, after N times of "ralph-sq send system:subtask_completed" trigger continue (None = no limit)
    continue_when_subtask: Optional[int] = None


@dataclass
class RepeatSequence:
    """A sequence of steps that can be repeated."""

    steps: list[SequenceStep] = field(default_factory=list)
    repeat: int = 1


@dataclass
class RalphConfig:
    """Complete configuration from ralph.yaml."""

    roles: dict[str, Role] = field(default_factory=dict)
    repeat_sequences: list[RepeatSequence] = field(default_factory=list)
    interactive: bool = False
    language: Optional[str] = None

    @classmethod
    def load(cls, config_path: str | Path) -> "RalphConfig":
        """
        Load configuration from a YAML file.

        Args:
            config_path: Path to ralph.yaml file

        Returns:
            RalphConfig instance

        Raises:
            FileNotFoundError: If config file doesn't exist
            yaml.YAMLError: If YAML parsing fails
            ValueError: If YAML content does not conform to the expected schema
                        (e.g. unexpected keys or wrong types).
        """
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Configuration file not found: {path}")

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not data:
            return cls()

        # First, validate structure strictly with pydantic.
        try:
            model = _RalphConfigModel.model_validate(data)
        except ValidationError as exc:
            raise ValueError(f"Invalid configuration in {path}: {exc}") from exc

        # Parse global options
        interactive = model.interactive
        language = model.language

        # Parse roles from top-level `roles` (if provided)
        roles: dict[str, Role] = {}
        if model.roles:
            for role_def in model.roles:
                roles[role_def.role] = Role(
                    name=role_def.role,
                    prompt_file=role_def.prompt_file,
                )

        # Backward compatibility: if roles are not defined in 'roles' section,
        # collect them from repeat_sequences (using step.prompt_file).
        if model.repeat_sequence:
            for seq in model.repeat_sequence:
                for step in seq.sequence:
                    role_name = step.role
                    if role_name not in roles:
                        roles[role_name] = Role(
                            name=role_name,
                            prompt_file=step.prompt_file,
                        )

        # Parse repeat_sequences into dataclasses
        repeat_sequences: list[RepeatSequence] = []
        if model.repeat_sequence:
            for seq in model.repeat_sequence:
                steps: list[SequenceStep] = []
                for step in seq.sequence:
                    prompt = step.prompt
                    # Convert empty strings to None
                    if prompt == "":
                        prompt = None
                    steps.append(
                        SequenceStep(
                            role=step.role,
                            prompt=prompt,
                            new_session=step.new_session,
                            interactive=step.interactive,
                            max_conversation=step.max_conversation,
                            continue_when_subtask=step.continue_when_subtask,
                        )
                    )

                repeat_sequences.append(RepeatSequence(steps=steps, repeat=seq.repeat))

        return cls(
            roles=roles,
            repeat_sequences=repeat_sequences,
            interactive=interactive,
            language=language,
        )
    
    def get_role_prompt(self, role_name: str, working_directory: Optional[str] = None) -> Optional[str]:
        """
        Load prompt content for a role.
        
        Args:
            role_name: Name of the role
            working_directory: Base directory for resolving prompt_file paths
            
        Returns:
            Prompt content as string, or None if role not found or no prompt_file
        """
        if role_name not in self.roles:
            return None
        
        role = self.roles[role_name]
        if not role.prompt_file:
            return None
        
        if working_directory:
            path = Path(working_directory) / role.prompt_file
        else:
            path = Path(role.prompt_file)
        
        if not path.exists():
            return None
        
        return path.read_text(encoding='utf-8')
