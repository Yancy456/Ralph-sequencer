"""
Configuration parser for ralph.yaml.

This module provides functionality to load and parse the ralph.yaml
configuration file, which defines roles and repeat sequences.
"""

import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Any


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
        """
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Configuration file not found: {path}")
        
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        
        if not data:
            return cls()
        
        # Parse roles
        roles = {}
        if "roles" in data and isinstance(data["roles"], list):
            for role_data in data["roles"]:
                if isinstance(role_data, dict) and "role" in role_data:
                    role_name = role_data["role"]
                    prompt_file = role_data.get("prompt_file")
                    roles[role_name] = Role(name=role_name, prompt_file=prompt_file)
        
        # Parse repeat_sequences
        repeat_sequences = []
        if "repeat_sequence" in data and isinstance(data["repeat_sequence"], list):
            for seq_data in data["repeat_sequence"]:
                if isinstance(seq_data, dict) and "sequence" in seq_data:
                    steps = []
                    sequence_list = seq_data["sequence"]
                    if isinstance(sequence_list, list):
                        for step_data in sequence_list:
                            if isinstance(step_data, dict) and "role" in step_data:
                                prompt = step_data.get("prompt")
                                # Convert empty strings to None
                                if prompt == "":
                                    prompt = None
                                step = SequenceStep(
                                    role=step_data["role"],
                                    prompt=prompt,
                                    new_session=step_data.get("new_session", True),
                                )
                                steps.append(step)
                    
                    repeat = seq_data.get("repeat", 1)
                    repeat_sequences.append(RepeatSequence(steps=steps, repeat=repeat))
        
        return cls(roles=roles, repeat_sequences=repeat_sequences)
    
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
