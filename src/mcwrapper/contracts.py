"""Stable public contracts shared by MCwrapper commands."""

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Dict, List, Mapping


ACTION_PLAN_SCHEMA_VERSION = "1.0"
MUTATION_CAPABLE_PROFILES = frozenset({"development", "production"})


class ExitCode(IntEnum):
    """Stable process exit statuses for the modern command-line interface."""

    SUCCESS = 0
    USAGE = 2
    SAFETY_REFUSAL = 3
    INVALID_CONFIGURATION = 4
    EXTERNAL_FAILURE = 5
    INTERNAL_ERROR = 70


class MutationRefusedError(RuntimeError):
    """Raised when a command attempts a mutation without explicit authority."""


@dataclass(frozen=True)
class ExecutionPolicy:
    """Resolved execution settings for one CLI invocation."""

    profile: str = "read-only"
    execute: bool = False

    @property
    def dry_run(self) -> bool:
        """Return whether mutating actions must remain plans only."""
        return not self.execute

    def require_mutation(self) -> None:
        """Refuse a mutation unless execution and a capable profile are explicit."""
        if not self.execute:
            raise MutationRefusedError(
                "mutation refused: dry-run is the default; pass --execute to opt in"
            )
        if self.profile not in MUTATION_CAPABLE_PROFILES:
            raise MutationRefusedError(
                "mutation refused: --execute also requires an explicit "
                "mutation-capable profile"
            )


@dataclass(frozen=True)
class PlannedAction:
    """One deterministic action in an action-plan document."""

    kind: str
    target: str
    description: str
    mutating: bool
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Return the stable JSON representation of this action."""
        return {
            "kind": self.kind,
            "target": self.target,
            "description": self.description,
            "mutating": self.mutating,
            "parameters": dict(self.parameters),
        }


@dataclass(frozen=True)
class ActionPlan:
    """Versioned, JSON-serializable plan shared by current and future commands."""

    command: str
    profile: str
    dry_run: bool
    actions: List[PlannedAction] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Return the version-1 action-plan schema as plain JSON values."""
        return {
            "schema_version": ACTION_PLAN_SCHEMA_VERSION,
            "command": self.command,
            "profile": self.profile,
            "dry_run": self.dry_run,
            "actions": [action.to_dict() for action in self.actions],
        }
