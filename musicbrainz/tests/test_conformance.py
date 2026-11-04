"""The rules every provider follows, checked by the SDK on this one (musizeer_sdk.conformance)."""
from musizeer_sdk.conformance import check_provider
from musizeer_sdk.context import StaticProviderContext

from musizeer_provider_musicbrainz import MusicBrainzMetadataProvider


def test_the_provider_follows_the_generic_rules_of_the_contract():
    check_provider(MusicBrainzMetadataProvider(StaticProviderContext()))
