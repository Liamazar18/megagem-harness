"""A small immutable, pickleable mapping for cards and bot snapshots."""

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Generic, TypeVar

K = TypeVar("K")
V = TypeVar("V")


# A simplified implementation of an immutable dictionary
# Key-value pairs cannot be added, removed, nor replaced

# frozen = True: prevents reassigning instance attributes
# slots = True: saves memory and restricts attributes
# init = False: prevents dataclass decorator from generating an __init__ method
# eq = False: prevents dataclass decorator from generating an __eq__method

# frozen = True prevents reassignment of attributes, but does not recursively
# freeze the contents of the attributes. This is why storing _items as a tuple
# is necessary

# Mapping base class does not provide functionality for __setitem__, only __getitem__,
# so a FrozenMap is read-only

# Note: you are not prevented from using .__setattr__ to modify the _items attribute of a 
# frozen map. However, we will check for this in your implementations and reject programs 
# that use it!

@dataclass(frozen=True, slots=True, init=False, eq=False)
class FrozenMap(Mapping[K, V], Generic[K, V]):
    # Nested tuple, with an arbitrary number of inner tuples
    # Outer tuples make it impossible to add/remove entries, 
    # inner tuples prevent replacing individual key-value components
    _items: tuple[tuple[K, V], ...] 

    def __init__(self, items: Mapping[K, V] | Iterable[tuple[K, V]] = ()) -> None:
        # Object.__setattr__ bypasses the frozen dataclass assignment restriction
        object.__setattr__(self, "_items", tuple(dict(items).items()))

    # __getitem__ loops through items, rather than using a hash
    # so it has O(n) performance, rather than O(1).
    # Not much of a problem for our small dictionaries
    def __getitem__(self, key: K) -> V:
        for item_key, value in self._items:
            if item_key == key:
                return value
        raise KeyError(key)

    def __iter__(self) -> Iterator[K]:
        return (key for key, _ in self._items)

    def __len__(self) -> int:
        return len(self._items)

    # Makes the FrozenMap hashable
    # Can be used as a key in another dictionary or element of a set.
    # Necessary for Mapping __eq__ implementation
    def __hash__(self) -> int:
        return hash(frozenset(self._items))
