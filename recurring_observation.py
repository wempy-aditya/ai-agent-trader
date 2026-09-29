"""Configuration boundary for future bounded recurring observation.

This module defines and validates limits only. It does not start a scheduler.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RecurringObservationConfig:
    max_cycles: int = 6
    cadence_seconds: int = 3600
    execute: bool = False
    scheduler: str = "none"


def validate_config(config: RecurringObservationConfig) -> list[str]:
    errors: list[str] = []
    if not 1 <= config.max_cycles <= 24:
        errors.append("max_cycles must be between 1 and 24")
    if config.cadence_seconds < 3600:
        errors.append("cadence_seconds must be at least 3600")
    if config.scheduler != "none":
        errors.append("scheduler must be none for bounded local observation")
    if config.execute:
        errors.append("execute must remain false until separate recurring-loop approval")
    return errors
