"""The rules every provider follows, checked by the SDK on this one (musizeer_sdk.conformance)."""
from musizeer_sdk.conformance import check_provider
from musizeer_sdk.context import StaticProviderContext

from musizeer_provider_local import LocalStorageProvider


def test_the_provider_follows_the_generic_rules_of_the_contract():
    check_provider(LocalStorageProvider(StaticProviderContext()))


def test_the_library_folder_is_a_declared_folder_setting():
    from musizeer_sdk.conformance import folder_violations

    provider = LocalStorageProvider(StaticProviderContext())

    assert provider.library_folder_setting() == "root_dir"
    assert folder_violations(provider) == []
