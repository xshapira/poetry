from __future__ import annotations

import hashlib
import json

from pathlib import Path
from typing import TYPE_CHECKING

from poetry.core.packages.utils.link import Link

from poetry.installation.chooser import InvalidWheelName
from poetry.installation.chooser import Wheel


if TYPE_CHECKING:

    from poetry.config.config import Config
    from poetry.utils.env import Env


class Chef:
    def __init__(self, config: Config, env: Env) -> None:
        self._config = config
        self._env = env
        self._cache_dir = (
            Path(config.get("cache-dir")).expanduser().joinpath("artifacts")
        )

    def prepare(self, archive: Path) -> Path:
        return archive

    def prepare_sdist(self, archive: Path) -> Path:
        return archive

    def prepare_wheel(self, archive: Path) -> Path:
        return archive

    def should_prepare(self, archive: Path) -> bool:
        return not self.is_wheel(archive)

    def is_wheel(self, archive: Path) -> bool:
        return archive.suffix == ".whl"

    def get_cached_archive_for_link(self, link: Link) -> Link | None:
        # If the archive is already a wheel, there is no need to cache it.
        if link.is_wheel:
            return link

        archives = self.get_cached_archives_for_link(link)

        if not archives:
            return link

        candidates = []
        for archive in archives:
            if not archive.is_wheel:
                candidates.append((float("inf"), archive))
                continue

            try:
                wheel = Wheel(archive.filename)
            except InvalidWheelName:
                continue

            if not wheel.is_supported_by_environment(self._env):
                continue

            candidates.append(
                (wheel.get_minimum_supported_index(self._env.supported_tags), archive),
            )

        return min(candidates)[1] if candidates else link

    def get_cached_archives_for_link(self, link: Link) -> list[Link]:
        cache_dir = self.get_cache_directory_for_link(link)

        archive_types = ["whl", "tar.gz", "tar.bz2", "bz2", "zip"]
        links = []
        for archive_type in archive_types:
            links.extend(
                Link(archive.as_uri())
                for archive in cache_dir.glob(f"*.{archive_type}")
            )

        return links

    def get_cache_directory_for_link(self, link: Link) -> Path:
        key_parts = {"url": link.url_without_fragment}

        if link.hash_name is not None and link.hash is not None:
            key_parts[link.hash_name] = link.hash

        if link.subdirectory_fragment:
            key_parts["subdirectory"] = link.subdirectory_fragment

        key_parts["interpreter_name"] = self._env.marker_env["interpreter_name"]
        key_parts["interpreter_version"] = "".join(
            self._env.marker_env["interpreter_version"].split(".")[:2]
        )

        key = hashlib.sha256(
            json.dumps(
                key_parts, sort_keys=True, separators=(",", ":"), ensure_ascii=True
            ).encode("ascii")
        ).hexdigest()

        split_key = [key[:2], key[2:4], key[4:6], key[6:]]

        return self._cache_dir.joinpath(*split_key)
