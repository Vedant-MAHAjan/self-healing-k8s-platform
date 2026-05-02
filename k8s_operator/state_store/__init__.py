"""Persistent feedback and state store for the autonomous control plane."""

from .store import SQLiteStateStore

__all__ = ["SQLiteStateStore"]