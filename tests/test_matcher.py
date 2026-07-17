"""Tests for the HostMatcher engine."""

from __future__ import annotations

import pytest

from pxeos.matcher import HostMatcher
from pxeos.models import HostRule


def _rule(**kwargs) -> HostRule:
    """Convenience factory with sensible defaults."""
    kwargs.setdefault("profile", "default")
    kwargs.setdefault("os_family", "fedora")
    kwargs.setdefault("os_version", "41")
    return HostRule(**kwargs)


# ---- Tier 0: exact MAC match ----


class TestExactMacMatch:

    def test_case_insensitive(self):
        rule = _rule(mac="aa:bb:cc:dd:ee:ff")
        matcher = HostMatcher([rule])
        result = matcher.match(mac="AA:BB:CC:DD:EE:FF")
        assert result is rule

    def test_dashes_normalised(self):
        rule = _rule(mac="aa-bb-cc-dd-ee-ff")
        matcher = HostMatcher([rule])
        result = matcher.match(mac="aa:bb:cc:dd:ee:ff")
        assert result is rule

    def test_no_match_different_mac(self):
        rule = _rule(mac="aa:bb:cc:dd:ee:ff")
        matcher = HostMatcher([rule])
        result = matcher.match(mac="11:22:33:44:55:66")
        assert result is None


# ---- Tier 1: MAC prefix ----


class TestMacPrefixMatch:

    def test_prefix_matches(self):
        rule = _rule(mac_prefix="aa:bb:cc")
        matcher = HostMatcher([rule])
        result = matcher.match(mac="aa:bb:cc:11:22:33")
        assert result is rule

    def test_prefix_no_match(self):
        rule = _rule(mac_prefix="aa:bb:cc")
        matcher = HostMatcher([rule])
        result = matcher.match(mac="ff:ee:dd:11:22:33")
        assert result is None


# ---- Tier 2: hostname glob ----


class TestHostnameGlobMatch:

    def test_glob_matches(self):
        rule = _rule(hostname_pattern="web-*")
        matcher = HostMatcher([rule])
        assert matcher.match(hostname="web-01") is rule

    def test_glob_no_match(self):
        rule = _rule(hostname_pattern="web-*")
        matcher = HostMatcher([rule])
        assert matcher.match(hostname="db-01") is None


# ---- Tier 3: subnet CIDR ----


class TestSubnetCidrMatch:

    def test_ip_in_cidr(self):
        rule = _rule(subnet="10.0.5.0/24")
        matcher = HostMatcher([rule])
        assert matcher.match(subnet="10.0.5.100") is rule

    def test_ip_outside_cidr(self):
        rule = _rule(subnet="10.0.5.0/24")
        matcher = HostMatcher([rule])
        assert matcher.match(subnet="10.0.6.100") is None


# ---- Tier 4: serial ----


class TestSerialMatch:

    def test_serial_matches(self):
        rule = _rule(serial="SN-123-ABC")
        matcher = HostMatcher([rule])
        assert matcher.match(serial="SN-123-ABC") is rule

    def test_serial_no_match(self):
        rule = _rule(serial="SN-123-ABC")
        matcher = HostMatcher([rule])
        assert matcher.match(serial="SN-999-XYZ") is None


# ---- Tier 5: group ----


class TestGroupMatch:

    def test_group_in_list(self):
        rule = _rule(group="servers")
        matcher = HostMatcher([rule])
        assert matcher.match(groups=["servers", "production"]) is rule

    def test_group_not_in_list(self):
        rule = _rule(group="servers")
        matcher = HostMatcher([rule])
        assert matcher.match(groups=["desktops"]) is None


# ---- Tier 6: arch ----


class TestArchMatch:

    def test_arch_matches(self):
        rule = _rule(arch="x86_64")
        matcher = HostMatcher([rule])
        assert matcher.match(arch="x86_64") is rule

    def test_arch_case_insensitive(self):
        rule = _rule(arch="X86_64")
        matcher = HostMatcher([rule])
        assert matcher.match(arch="x86_64") is rule


# ---- Tier 7: default (no criteria) ----


class TestDefaultRule:

    def test_default_matches_when_nothing_else(self):
        default_rule = _rule(profile="fallback")
        matcher = HostMatcher([default_rule])
        assert matcher.match(mac="aa:bb:cc:dd:ee:ff") is default_rule

    def test_default_loses_to_specific(self):
        default_rule = _rule(profile="fallback", priority=1)
        specific_rule = _rule(
            profile="specific", mac="aa:bb:cc:dd:ee:ff", priority=999
        )
        matcher = HostMatcher([default_rule, specific_rule])
        result = matcher.match(mac="aa:bb:cc:dd:ee:ff")
        assert result is specific_rule


# ---- Ordering tests ----


class TestOrdering:

    def test_priority_ordering_same_tier(self):
        """Within the same tier, lower priority number wins."""
        high = _rule(
            profile="high", hostname_pattern="web-*", priority=10
        )
        low = _rule(
            profile="low", hostname_pattern="web-*", priority=50
        )
        matcher = HostMatcher([low, high])
        result = matcher.match(hostname="web-01")
        assert result is high

    def test_tier_beats_priority(self):
        """MAC match (tier 0) wins over hostname match (tier 2)
        even when hostname rule has a lower priority number."""
        mac_rule = _rule(
            profile="mac",
            mac="aa:bb:cc:dd:ee:ff",
            priority=999,
        )
        hostname_rule = _rule(
            profile="hostname",
            hostname_pattern="web-*",
            priority=1,
        )
        matcher = HostMatcher([mac_rule, hostname_rule])
        result = matcher.match(
            mac="aa:bb:cc:dd:ee:ff", hostname="web-01"
        )
        assert result is mac_rule


# ---- No match ----


class TestNoMatch:

    def test_returns_none_when_nothing_matches(self):
        rule = _rule(mac="aa:bb:cc:dd:ee:ff")
        matcher = HostMatcher([rule])
        assert matcher.match(mac="11:22:33:44:55:66") is None

    def test_empty_rules_returns_none(self):
        matcher = HostMatcher([])
        assert matcher.match(mac="aa:bb:cc:dd:ee:ff") is None
