"""A small immutable, pickleable mapping for cards and bot snapshots."""

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Generic, TypeVar

K = TypeVar("K")
V = TypeVar("V")


# A read-only mapping whose entries cannot be added, removed, or replaced.
#
# frozen=True prevents ordinary assignment to instance attributes.
# slots=True saves memory and restricts the available instance attributes.
# init=False keeps the custom __init__ method instead of generating one.
# eq=False preserves Mapping's equality comparison instead of generating one.
#
# Freezing a dataclass is shallow. Nested tuples protect the entry structure,
# but mutable objects stored as keys or values are not recursively frozen.
# Mapping supplies read-only operations and does not implement __setitem__.
@dataclass(frozen=True, slots=True, init=False, eq=False)
class FrozenMap(Mapping[K, V], Generic[K, V]):
    # The outer tuple fixes the entries; inner tuples fix each key-value pair.
    _items: tuple[tuple[K, V], ...] 

    def __init__(self, items: Mapping[K, V] | Iterable[tuple[K, V]] = ()) -> None:
        # Use object.__setattr__ to initialize the frozen instance.
        object.__setattr__(self, "_items", tuple(dict(items).items()))

    # Linear lookup is O(n), which is sufficient for these small mappings.
    def __getitem__(self, key: K) -> V:
        for item_key, value in self._items:
            if item_key == key:
                return value
        raise KeyError(key)

    def __iter__(self) -> Iterator[K]:
        return (key for key, _ in self._items)

    def __len__(self) -> int:
        return len(self._items)

    # Hash independently of entry order to match Mapping's equality semantics.
    # Using this mapping as a key or set member requires hashable keys and values.
    # Hashing is not required for Mapping's equality comparison.
    def __hash__(self) -> int:
        return hash(frozenset(self._items))
