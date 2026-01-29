"""
Exceptions used by ralph-py.
"""


class RalphExitRequested(Exception):
    """Raised when the model invokes a Bash command starting with 'ralph-py exit' to exit the current loop."""


class RalphContinueRequested(Exception):
    """Raised when the model invokes a Bash command starting with 'ralph-py continue' to skip the current step and continue the loop."""
