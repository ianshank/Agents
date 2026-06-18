"""A tiny, generic plugin registry.

Components register under a string ``type`` name; config selects them by that
name. Aliases let a renamed component keep resolving its old name, so configs
written against an earlier version keep working.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Generic, TypeVar

T = TypeVar("T")


class RegistryError(KeyError):
    pass


class Registry(Generic[T]):
    def __init__(self, kind: str) -> None:
        self.kind = kind
        self._reg: dict[str, type[T]] = {}
        self._aliases: dict[str, str] = {}

    def register(self, name: str, *, aliases: Iterable[str] = ()):  # decorator
        def deco(cls: type[T]) -> type[T]:
            self.register_class(name, cls, aliases=aliases)
            return cls

        return deco

    def register_class(self, name: str, cls: type[T], *, aliases: Iterable[str] = ()) -> None:
        if name in self._reg and self._reg[name] is not cls:
            raise RegistryError(f"{self.kind} '{name}' already registered")
        self._reg[name] = cls
        for alias in aliases:
            self._aliases[alias] = name

    def resolve(self, name: str) -> str:
        return self._aliases.get(name, name)

    def get(self, name: str) -> type[T]:
        key = self.resolve(name)
        if key not in self._reg:
            raise RegistryError(
                f"Unknown {self.kind} '{name}'. Available: {self.names()}"
            )
        return self._reg[key]

    def create(self, name: str, params: dict | None = None) -> T:
        return self.get(name)(**(params or {}))

    def names(self) -> list[str]:
        return sorted(self._reg)

    def __contains__(self, name: str) -> bool:
        return self.resolve(name) in self._reg
