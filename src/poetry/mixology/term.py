from __future__ import annotations

import functools

from typing import TYPE_CHECKING

from poetry.mixology.set_relation import SetRelation


if TYPE_CHECKING:
    from poetry.core.packages.dependency import Dependency
    from poetry.core.semver.helpers import VersionTypes


class Term:
    """
    A statement about a package which is true or false for a given selection of
    package versions.

    See https://github.com/dart-lang/pub/tree/master/doc/solver.md#term.
    """

    def __init__(self, dependency: Dependency, is_positive: bool) -> None:
        self._dependency = dependency
        self._positive = is_positive

    @property
    def inverse(self) -> Term:
        return Term(self._dependency, not self.is_positive())

    @property
    def dependency(self) -> Dependency:
        return self._dependency

    @property
    def constraint(self) -> VersionTypes:
        return self._dependency.constraint

    def is_positive(self) -> bool:
        return self._positive

    def satisfies(self, other: Term) -> bool:
        """
        Returns whether this term satisfies another.
        """
        return (
            self.dependency.complete_name == other.dependency.complete_name
            and self.relation(other) == SetRelation.SUBSET
        )

    @functools.lru_cache(maxsize=None)
    def relation(self, other: Term) -> int:
        """
        Returns the relationship between the package versions
        allowed by this term and another.
        """
        if self.dependency.complete_name != other.dependency.complete_name:
            raise ValueError(f"{other} should refer to {self.dependency.complete_name}")

        other_constraint = other.constraint

        if other.is_positive():
            if self.is_positive():
                if not self._compatible_dependency(other.dependency):
                    return SetRelation.DISJOINT

                # foo ^1.5.0 is a subset of foo ^1.0.0
                if other_constraint.allows_all(self.constraint):
                    return SetRelation.SUBSET

                # foo ^2.0.0 is disjoint with foo ^1.0.0
                if not self.constraint.allows_any(other_constraint):
                    return SetRelation.DISJOINT

            else:
                if not self._compatible_dependency(other.dependency):
                    return SetRelation.OVERLAPPING

                # not foo ^1.0.0 is disjoint with foo ^1.5.0
                if self.constraint.allows_all(other_constraint):
                    return SetRelation.DISJOINT

        elif self.is_positive():
            if not self._compatible_dependency(other.dependency):
                return SetRelation.SUBSET

            # foo ^2.0.0 is a subset of not foo ^1.0.0
            if not other_constraint.allows_any(self.constraint):
                return SetRelation.SUBSET

            # foo ^1.5.0 is disjoint with not foo ^1.0.0
            if other_constraint.allows_all(self.constraint):
                return SetRelation.DISJOINT

        else:
            if not self._compatible_dependency(other.dependency):
                return SetRelation.OVERLAPPING

            # not foo ^1.0.0 is a subset of not foo ^1.5.0
            if self.constraint.allows_all(other_constraint):
                return SetRelation.SUBSET


        return SetRelation.OVERLAPPING

    @functools.lru_cache(maxsize=None)
    def intersect(self, other: Term) -> Term | None:
        """
        Returns a Term that represents the packages
        allowed by both this term and another
        """
        if self.dependency.complete_name != other.dependency.complete_name:
            raise ValueError(f"{other} should refer to {self.dependency.complete_name}")

        if self._compatible_dependency(other.dependency):
            if self.is_positive() != other.is_positive():
                # foo ^1.0.0 ∩ not foo ^1.5.0 → foo >=1.0.0 <1.5.0
                positive = self if self.is_positive() else other
                negative = other if self.is_positive() else self

                return self._non_empty_term(
                    positive.constraint.difference(negative.constraint), True
                )
            elif self.is_positive():
                # foo ^1.0.0 ∩ foo >=1.5.0 <3.0.0 → foo ^1.5.0
                return self._non_empty_term(
                    self.constraint.intersect(other.constraint), True
                )
            else:
                # not foo ^1.0.0 ∩ not foo >=1.5.0 <3.0.0 → not foo >=1.0.0 <3.0.0
                return self._non_empty_term(
                    self.constraint.union(other.constraint), False
                )
        elif self.is_positive() != other.is_positive():
            return self if self.is_positive() else other
        else:
            return None

    def difference(self, other: Term) -> Term:
        """
        Returns a Term that represents packages
        allowed by this term and not by the other
        """
        return self.intersect(other.inverse)

    def _compatible_dependency(self, other: Dependency) -> bool:
        return (
            self.dependency.is_root
            or other.is_root
            or other.is_same_package_as(self.dependency)
        )

    def _non_empty_term(
        self, constraint: VersionTypes, is_positive: bool
    ) -> Term | None:
        if constraint.is_empty():
            return None

        return Term(self.dependency.with_constraint(constraint), is_positive)

    def __str__(self) -> str:
        prefix = "" if self.is_positive() else "not "
        return f"{prefix}{self._dependency}"

    def __repr__(self) -> str:
        return f"<Term {self!s}>"
