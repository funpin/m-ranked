"""Rendezvous placement inside capability pools."""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from collector_target.model import Platform
from collector_target.placement import (
    Member,
    Placement,
    PlacementError,
    filter_accounts,
    movement,
    parse_membership,
)


THREE = "server-1:telegram|vk|max|rutube,server-2:telegram|vk|rutube,server-3:telegram|vk|rutube"


def _placement(membership: str = THREE, **replication: int) -> Placement:
    factors = {platform: 1 for platform in Platform}
    for name, value in replication.items():
        factors[Platform(name)] = value
    return Placement(parse_membership(membership), factors)


def _accounts(count: int = 2000) -> list[UUID]:
    return [uuid4() for _ in range(count)]


# --- capability pools -------------------------------------------------------

def test_a_platform_is_only_offered_to_hosts_that_can_serve_it() -> None:
    """MAX needs a user session bound to a phone; only one host has it.

    Hashing over the whole membership would hand MAX accounts to hosts without
    credentials, and those accounts would simply go uncollected.
    """
    placement = _placement()
    assert [item.server_id for item in placement.pool(Platform.MAX)] == ["server-1"]
    for account in _accounts(200):
        assert placement.owners(Platform.MAX, account) == ("server-1",)


def test_a_platform_no_member_can_serve_is_reported_not_silently_dropped() -> None:
    placement = _placement("server-1:telegram|vk")
    assert set(placement.uncovered()) == {Platform.MAX, Platform.RUTUBE}
    assert Platform.TELEGRAM not in placement.uncovered()


def test_a_pool_smaller_than_the_requested_factor_is_a_degraded_state() -> None:
    """Fewer copies than asked for is worth seeing, not worth refusing."""
    placement = Placement(
        parse_membership(THREE),
        {Platform.TELEGRAM: 1, Platform.VK: 1, Platform.MAX: 3, Platform.RUTUBE: 1},
    )
    assert placement.effective_replication(Platform.MAX) == 1
    assert placement.underprovisioned() == (Platform.MAX,)
    # Placement still answers; it does not refuse to run.
    assert len(placement.owners(Platform.MAX, uuid4())) == 1


# --- determinism ------------------------------------------------------------

def test_every_host_computes_the_same_owners_without_asking_anyone() -> None:
    accounts = _accounts(300)
    first, second = _placement(), _placement()
    for account in accounts:
        for platform in Platform:
            assert first.owners(platform, account) == second.owners(platform, account)


def test_member_order_in_the_configuration_does_not_change_the_answer() -> None:
    """The membership list is distributed config; order must not matter."""
    forward = _placement()
    backward = _placement(
        "server-3:telegram|vk|rutube,server-1:telegram|vk|max|rutube,server-2:telegram|vk|rutube"
    )
    for account in _accounts(300):
        assert set(forward.owners(Platform.VK, account)) == set(
            backward.owners(Platform.VK, account)
        )


# --- replication factors ----------------------------------------------------

def test_replication_of_one_is_pure_sharding() -> None:
    placement = _placement()
    accounts = _accounts()
    for account in accounts:
        assert len(placement.owners(Platform.VK, account)) == 1
    owners = {placement.owners(Platform.VK, account)[0] for account in accounts}
    assert len(owners) == 3


def test_replication_of_two_puts_every_account_on_exactly_two_hosts() -> None:
    placement = Placement(
        parse_membership(THREE),
        {Platform.TELEGRAM: 2, Platform.VK: 1, Platform.MAX: 1, Platform.RUTUBE: 1},
    )
    for account in _accounts(500):
        owners = placement.owners(Platform.TELEGRAM, account)
        assert len(owners) == 2
        assert len(set(owners)) == 2


def test_replication_equal_to_the_pool_is_full_duplication() -> None:
    placement = Placement(
        parse_membership(THREE),
        {Platform.TELEGRAM: 3, Platform.VK: 1, Platform.MAX: 1, Platform.RUTUBE: 1},
    )
    for account in _accounts(200):
        assert len(placement.owners(Platform.TELEGRAM, account)) == 3


def test_accounts_spread_evenly_across_the_pool() -> None:
    placement = _placement()
    accounts = _accounts(3000)
    counts: dict[str, int] = {}
    for account in accounts:
        owner = placement.owners(Platform.VK, account)[0]
        counts[owner] = counts.get(owner, 0) + 1
    share = len(accounts) / 3
    # Rendezvous hashing is not a perfect partition; ten per cent is ample.
    for owner, count in counts.items():
        assert abs(count - share) < share * 0.10, (owner, count)


# --- rebalancing ------------------------------------------------------------

def test_adding_a_host_moves_about_one_share_rather_than_reshuffling() -> None:
    """The reason for rendezvous hashing rather than modulo.

    A modulo assignment would move most accounts whenever the member count
    changes, and every moved account loses the refresh state its old host held.
    """
    accounts = _accounts(3000)
    before = _placement()
    after = _placement(THREE + ",server-4:telegram|vk|rutube")
    moved = movement(before, after, Platform.VK, accounts)
    assert 0.15 < moved < 0.35


def test_removing_a_host_only_moves_the_accounts_it_held() -> None:
    accounts = _accounts(2000)
    before = _placement()
    after = _placement("server-1:telegram|vk|max|rutube,server-2:telegram|vk|rutube")
    held = {
        account for account in accounts
        if before.owners(Platform.VK, account)[0] == "server-3"
    }
    for account in accounts:
        if account not in held:
            assert before.owners(Platform.VK, account) == after.owners(
                Platform.VK, account
            )


# --- filtering --------------------------------------------------------------

class _Account:
    def __init__(self, account_id: UUID) -> None:
        self.id = account_id


def test_filtering_keeps_exactly_the_accounts_this_host_owns() -> None:
    placement = _placement()
    accounts = [_Account(uuid4()) for _ in range(500)]
    kept = {
        server: {item.id for item in filter_accounts(
            accounts, placement, server, Platform.VK,
        )}
        for server in ("server-1", "server-2", "server-3")
    }
    # Replication of one: the three sets partition the accounts exactly.
    assert sum(len(item) for item in kept.values()) == len(accounts)
    assert set().union(*kept.values()) == {item.id for item in accounts}
    assert not kept["server-1"] & kept["server-2"]


def test_a_host_outside_the_membership_owns_nothing() -> None:
    placement = _placement()
    accounts = [_Account(uuid4()) for _ in range(100)]
    assert filter_accounts(accounts, placement, "server-9", Platform.VK) == ()


def test_the_single_host_case_owns_everything() -> None:
    placement = Placement.single("server-1")
    accounts = [_Account(uuid4()) for _ in range(200)]
    for platform in Platform:
        assert len(filter_accounts(accounts, placement, "server-1", platform)) == 200


# --- configuration ----------------------------------------------------------

def test_membership_parsing_accepts_the_documented_shape() -> None:
    members = parse_membership(" server-1:telegram|VK , server-2:max ")
    assert members[0] == Member("server-1", frozenset({Platform.TELEGRAM, Platform.VK}))
    assert members[1] == Member("server-2", frozenset({Platform.MAX}))


@pytest.mark.parametrize(
    "value",
    ["", "server-1", "server-1:", ":telegram", "server-1:nosuchplatform", "   "],
)
def test_malformed_membership_is_rejected(value: str) -> None:
    with pytest.raises(PlacementError):
        parse_membership(value)


@pytest.mark.parametrize("server_id", ["", "Server-1", "server 1", "a" * 65, "-x"])
def test_invalid_server_id_is_rejected(server_id: str) -> None:
    with pytest.raises(PlacementError):
        Member(server_id, frozenset({Platform.VK}))


def test_duplicate_server_ids_are_rejected() -> None:
    with pytest.raises(PlacementError, match="duplicate"):
        _placement("server-1:vk,server-1:telegram")


def test_a_nonpositive_replication_factor_is_rejected() -> None:
    with pytest.raises(PlacementError, match="positive"):
        Placement(parse_membership("server-1:vk"), {Platform.VK: 0})


def test_empty_membership_is_rejected() -> None:
    with pytest.raises(PlacementError):
        Placement((), {Platform.VK: 1})
