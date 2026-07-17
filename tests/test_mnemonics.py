"""Tests for distro mnemonic aliases."""

from __future__ import annotations

import unittest

from pxeos.mnemonics import (
    BUILTIN_ALIASES,
    DistroAlias,
    MnemonicRegistry,
    list_mnemonics,
    resolve_mnemonic,
)


class TestDistroAlias(unittest.TestCase):

    def test_frozen(self):
        alias = DistroAlias("fedora", "fedora", "42")
        with self.assertRaises(AttributeError):
            alias.os_family = "debian"

    def test_equality(self):
        a = DistroAlias("fedora", "fedora", "42")
        b = DistroAlias("fedora", "fedora", "42")
        self.assertEqual(a, b)


class TestBuiltinAliases(unittest.TestCase):

    def test_fedora42_exists(self):
        self.assertIn("fedora42", BUILTIN_ALIASES)
        alias = BUILTIN_ALIASES["fedora42"]
        self.assertEqual(alias.os_family, "fedora")
        self.assertEqual(alias.vendor, "fedora")
        self.assertEqual(alias.version, "42")

    def test_rhel9_exists(self):
        alias = BUILTIN_ALIASES["rhel9"]
        self.assertEqual(alias.os_family, "fedora")
        self.assertEqual(alias.vendor, "rhel")
        self.assertEqual(alias.version, "9")

    def test_deb12_exists(self):
        alias = BUILTIN_ALIASES["deb12"]
        self.assertEqual(alias.os_family, "debian")
        self.assertEqual(alias.vendor, "debian")
        self.assertEqual(alias.version, "12")

    def test_bookworm_is_deb12(self):
        self.assertEqual(
            BUILTIN_ALIASES["bookworm"],
            BUILTIN_ALIASES["deb12"],
        )

    def test_ubuntu2404_exists(self):
        alias = BUILTIN_ALIASES["ubuntu2404"]
        self.assertEqual(alias.os_family, "ubuntu")
        self.assertEqual(alias.version, "24.04")

    def test_noble_is_ubuntu2404(self):
        self.assertEqual(
            BUILTIN_ALIASES["noble"],
            BUILTIN_ALIASES["ubuntu2404"],
        )

    def test_fbsd14_exists(self):
        alias = BUILTIN_ALIASES["fbsd14"]
        self.assertEqual(alias.os_family, "freebsd")
        self.assertEqual(alias.version, "14")

    def test_win11_exists(self):
        alias = BUILTIN_ALIASES["win11"]
        self.assertEqual(alias.os_family, "windows")
        self.assertEqual(alias.version, "11")

    def test_arch_exists(self):
        alias = BUILTIN_ALIASES["arch"]
        self.assertEqual(alias.os_family, "arch")
        self.assertEqual(alias.version, "latest")

    def test_rocky9_exists(self):
        alias = BUILTIN_ALIASES["rocky9"]
        self.assertEqual(alias.os_family, "fedora")
        self.assertEqual(alias.vendor, "rocky")

    def test_sles15_exists(self):
        alias = BUILTIN_ALIASES["sles15"]
        self.assertEqual(alias.os_family, "suse")

    def test_obsd76_exists(self):
        alias = BUILTIN_ALIASES["obsd76"]
        self.assertEqual(alias.os_family, "openbsd")

    def test_nbsd10_exists(self):
        alias = BUILTIN_ALIASES["nbsd10"]
        self.assertEqual(alias.os_family, "netbsd")


class TestMnemonicRegistry(unittest.TestCase):

    def setUp(self):
        self.reg = MnemonicRegistry()

    def test_resolve_builtin(self):
        alias = self.reg.resolve("fedora42")
        self.assertIsNotNone(alias)
        self.assertEqual(alias.os_family, "fedora")

    def test_resolve_case_insensitive(self):
        alias = self.reg.resolve("Fedora42")
        self.assertIsNotNone(alias)
        self.assertEqual(alias.os_family, "fedora")

    def test_resolve_strips_hyphens(self):
        alias = self.reg.resolve("fedora-42")
        self.assertIsNotNone(alias)
        self.assertEqual(alias.version, "42")

    def test_resolve_strips_underscores(self):
        alias = self.reg.resolve("fedora_42")
        self.assertIsNotNone(alias)

    def test_resolve_unknown_returns_none(self):
        self.assertIsNone(self.reg.resolve("zzzz999"))

    def test_resolve_empty_returns_none(self):
        self.assertIsNone(self.reg.resolve(""))

    def test_resolve_whitespace_returns_none(self):
        self.assertIsNone(self.reg.resolve("   "))

    def test_resolve_fallback_to_parse(self):
        alias = self.reg.resolve("fedora99")
        self.assertIsNotNone(alias)
        self.assertEqual(alias.os_family, "fedora")
        self.assertEqual(alias.vendor, "fedora")
        self.assertEqual(alias.version, "99")

    def test_resolve_parse_rhel(self):
        alias = self.reg.resolve("rhel10")
        self.assertIsNotNone(alias)
        self.assertEqual(alias.os_family, "fedora")
        self.assertEqual(alias.vendor, "rhel")

    def test_resolve_parse_deb(self):
        alias = self.reg.resolve("deb99")
        self.assertIsNotNone(alias)
        self.assertEqual(alias.os_family, "debian")
        self.assertEqual(alias.version, "99")

    def test_resolve_parse_ubuntu(self):
        alias = self.reg.resolve("ubuntu25.04")
        self.assertIsNotNone(alias)
        self.assertEqual(alias.os_family, "ubuntu")
        self.assertEqual(alias.version, "25.04")

    def test_resolve_parse_fbsd(self):
        alias = self.reg.resolve("fbsd15")
        self.assertIsNotNone(alias)
        self.assertEqual(alias.os_family, "freebsd")

    def test_resolve_parse_win(self):
        alias = self.reg.resolve("win12")
        self.assertIsNotNone(alias)
        self.assertEqual(alias.os_family, "windows")

    def test_resolve_parse_unknown_prefix(self):
        self.assertIsNone(self.reg.resolve("foobar42"))

    def test_register_custom(self):
        custom = DistroAlias("custom", "myvendor", "1.0")
        self.reg.register("myos1", custom)
        alias = self.reg.resolve("myos1")
        self.assertEqual(alias, custom)

    def test_register_overrides_builtin(self):
        custom = DistroAlias("custom", "custom", "99")
        self.reg.register("fedora42", custom)
        alias = self.reg.resolve("fedora42")
        self.assertEqual(alias.vendor, "custom")

    def test_list_aliases_sorted(self):
        aliases = self.reg.list_aliases()
        names = [n for n, _ in aliases]
        self.assertEqual(names, sorted(names))

    def test_list_aliases_not_empty(self):
        self.assertGreater(len(self.reg.list_aliases()), 0)

    def test_load_from_config(self):
        config = {
            "myos": {
                "os_family": "custom",
                "vendor": "myvendor",
                "version": "2.0",
            }
        }
        self.reg.load_from_config(config)
        alias = self.reg.resolve("myos")
        self.assertIsNotNone(alias)
        self.assertEqual(alias.os_family, "custom")
        self.assertEqual(alias.version, "2.0")

    def test_load_from_config_ignores_non_dict(self):
        config = {"bad": "not a dict"}
        self.reg.load_from_config(config)
        self.assertIsNone(self.reg.resolve("bad"))


class TestModuleFunctions(unittest.TestCase):

    def test_resolve_mnemonic(self):
        alias = resolve_mnemonic("rhel9")
        self.assertIsNotNone(alias)
        self.assertEqual(alias.os_family, "fedora")
        self.assertEqual(alias.vendor, "rhel")

    def test_resolve_mnemonic_unknown(self):
        self.assertIsNone(resolve_mnemonic("zzz"))

    def test_list_mnemonics_returns_tuples(self):
        mnemonics = list_mnemonics()
        self.assertIsInstance(mnemonics, list)
        for name, alias in mnemonics:
            self.assertIsInstance(name, str)
            self.assertIsInstance(alias, DistroAlias)
