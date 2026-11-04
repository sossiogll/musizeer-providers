# The MusicBrainz provider image. scripts/build.sh builds it; scripts/build-provider-image.sh of the main Musizeer
# repository puts the org.musizeer.provider.* labels on it, taken from the provider itself.
FROM ghcr.io/sossiogll/musizeer-provider-base:6

# Standard OCI labels: the development catalog entry is written from them. The provider label is what the provider
# calls itself (a test checks that it is).
LABEL org.opencontainers.image.description="Music metadata from the MusicBrainz open encyclopedia: search, artists, releases, ISRC lookup." \
      org.opencontainers.image.url="https://musicbrainz.org" \
      org.opencontainers.image.source="https://github.com/sossiogll/musizeer-providers" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later" \
      org.musizeer.provider.label="MusicBrainz"

COPY . /tmp/provider
RUN pip install /tmp/provider && rm -rf /tmp/provider

# The gateway appends --socket and --egress-socket.
ENTRYPOINT ["python", "-m", "musizeer_sdk.runner", "--provider", "musizeer_provider_musicbrainz:MusicBrainzMetadataProvider"]
