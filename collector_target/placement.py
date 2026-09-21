"""Which collector host owns which account.

Rendezvous hashing inside capability pools. Server 2 hands out only the member
list and a replication factor per platform; every host then computes the same
answer without asking anyone, so a host that cannot reach Server 2 keeps
collecting from its last known membership instead of stopping.

A certificate identifies a host, and credentials are per host and per platform:
MAX needs a user session bound to a phone, Telegram a session file. So the pool
for a platform is not every member, only the members that can actually reach
it. Hashing over the wrong pool would hand accounts to hosts that cannot serve
them, and the accounts would simply go uncollected.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Iterable, Mapping, Sequence
from uuid import UUID

from .model import Platform


SERVER_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class PlacementError(ValueError):
    """The membership or replication policy cannot be used as given."""


@dataclass(frozen=True, slots=True)
class Member:
    server_id: str
    platforms: frozenset[Platform]

    def __post_init__(self) -> None:
        if not SERVER_ID.match(self.server_id):
            raise PlacementError(f"invalid server id: {self.server_id!r}")
        if not self.platforms:
            raise PlacementError(f"{self.server_id} declares no platform")


def _score(account_id: UUID, server_id: str) -> bytes:
    """Rendezvous weight for one (account, host) pair.

    A keyed digest rather than a plain concatenation, so that a server id which
    happens to end with an account's prefix cannot collide with another pair.
    """
    digest = hashlib.blake2b(digest_size=16, key=b"mranked-placement-v1")
    digest.update(account_id.bytes)
    digest.update(b"\x00")
    digest.update(server_id.encode("utf-8"))
    return digest.digest()


@dataclass(frozen=True, slots=True)
class Placement:
    """A membership snapshot plus the replication factor per platform."""

    members: tuple[Member, ...]
    replication: Mapping[Platform, int]

    def __post_init__(self) -> None:
        if not self.members:
            raise PlacementError("membership must not be empty")
        ids = [member.server_id for member in self.members]
        if len(ids) != len(set(ids)):
            raise PlacementError("membership contains a duplicate server id")
        for platform, factor in self.replication.items():
            if factor < 1:
                raise PlacementError(
                    f"replication factor for {platform.value} must be positive"
                )

    @classmethod
    def single(cls, server_id: str) -> "Placement":
        """The one-host case: every platform, replication of one."""
        return cls(
            (Member(server_id, frozenset(Platform)),),
            {platform: 1 for platform in Platform},
        )

    def pool(self, platform: Platform) -> tuple[Member, ...]:
        return tuple(
            member for member in self.members if platform in member.platforms
        )

    def ranked(self, platform: Platform, account_id: UUID) -> tuple[str, ...]:
        """Hosts for this account, best first, within the platform's pool."""
        pool = self.pool(platform)
        # The server id breaks a digest tie, so the order is total and every
        # host computes the same one.
        return tuple(
            member.server_id
            for member in sorted(
                pool,
                key=lambda item: (_score(account_id, item.server_id), item.server_id),
                reverse=True,
            )
        )

    def owners(self, platform: Platform, account_id: UUID) -> tuple[str, ...]:
        """The top-R hosts, or the whole pool when it is smaller than R."""
        factor = self.replication.get(platform, 1)
        return self.ranked(platform, account_id)[:factor]

    def owns(self, server_id: str, platform: Platform, account_id: UUID) -> bool:
        return server_id in self.owners(platform, account_id)

    def effective_replication(self, platform: Platform) -> int:
        """How many copies this membership can actually produce.

        A pool smaller than the requested factor is not an error — it is a
        degraded state worth seeing, because it means the platform is running
        with fewer copies than the policy asked for.
        """
        return min(len(self.pool(platform)), self.replication.get(platform, 1))

    def underprovisioned(self) -> tuple[Platform, ...]:
        return tuple(
            platform for platform in Platform
            if self.effective_replication(platform)
            < self.replication.get(platform, 1)
        )

    def uncovered(self) -> tuple[Platform, ...]:
        """Platforms no member can serve; their accounts would go uncollected."""
        return tuple(
            platform for platform in Platform if not self.pool(platform)
        )


def parse_membership(value: str) -> tuple[Member, ...]:
    """Parse ``server-1:telegram|vk,server-2:max`` into members.

    The format is deliberately dull. Membership is distributed configuration,
    and a format that needs a parser needs a parser on every host.
    """
    members: list[Member] = []
    for entry in value.split(","):
        item = entry.strip()
        if not item:
            continue
        server_id, separator, platforms = item.partition(":")
        if not separator:
            raise PlacementError(f"membership entry needs platforms: {item!r}")
        names = [name.strip().lower() for name in platforms.split("|") if name.strip()]
        if not names:
            raise PlacementError(f"membership entry needs platforms: {item!r}")
        try:
            selected = frozenset(Platform(name) for name in names)
        except ValueError as error:
            raise PlacementError(f"unknown platform in {item!r}") from error
        members.append(Member(server_id.strip().lower(), selected))
    if not members:
        raise PlacementError("membership must not be empty")
    return tuple(members)


def filter_accounts(
    accounts: Iterable[object],
    placement: Placement,
    server_id: str,
    platform: Platform,
) -> tuple[object, ...]:
    """Keep only the accounts this host owns for this platform."""
    return tuple(
        account for account in accounts
        if placement.owns(server_id, platform, getattr(account, "id"))
    )


def movement(
    before: Placement, after: Placement, platform: Platform, accounts: Sequence[UUID],
) -> float:
    """Fraction of accounts whose owner set changes between two memberships.

    Used to show that adding or removing a host moves roughly one share of the
    accounts rather than reshuffling everything.
    """
    if not accounts:
        return 0.0
    moved = sum(
        1 for account in accounts
        if set(before.owners(platform, account)) != set(after.owners(platform, account))
    )
    return moved / len(accounts)
