"""Seed-health ranking and Raspberry Pi direct-play policy tests."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
import types

ROOT = Path(__file__).parents[1] / "custom_components" / "stremio_stream_bridge"
PACKAGE = "stremio_stream_bridge_seed_policy_test"

pkg = types.ModuleType(PACKAGE)
pkg.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = pkg

const_spec = spec_from_file_location(f"{PACKAGE}.const", ROOT / "const.py")
assert const_spec is not None and const_spec.loader is not None
CONST = module_from_spec(const_spec)
sys.modules[const_spec.name] = CONST
const_spec.loader.exec_module(CONST)

policy_spec = spec_from_file_location(f"{PACKAGE}.source_policy", ROOT / "source_policy.py")
assert policy_spec is not None and policy_spec.loader is not None
POLICY = module_from_spec(policy_spec)
sys.modules[policy_spec.name] = POLICY
policy_spec.loader.exec_module(POLICY)


def torrent(name: str, seeders: int, *, minimum: int = 5) -> dict:
    return {
        "name": name,
        "description": f"{seeders} seeders",
        "infoHash": (name.encode().hex() * 40)[:40],
        "_bridge_min_torrent_seeders": minimum,
    }


def parse_seeders(stream: dict) -> int:
    return int(str(stream["description"]).split()[0])


def test_healthy_torrent_soft_filters_one_and_two_seed_sources() -> None:
    weak_one = torrent("weak-one", 1)
    weak_two = torrent("weak-two", 2)
    healthy = torrent("healthy", 47)

    ordered = POLICY._apply_seed_policy(
        [weak_two, weak_one, healthy],
        prefer_direct_play=False,
        parse_seeders=parse_seeders,
        compatibility_rank=lambda stream: (0,),
    )

    assert ordered == [healthy]


def test_healthier_incompatible_source_does_not_replace_compatible_fallback() -> None:
    compatible_weak = torrent("compatible", 2)
    incompatible_healthy = torrent("incompatible", 80)

    ordered = POLICY._apply_seed_policy(
        [compatible_weak, incompatible_healthy],
        prefer_direct_play=True,
        parse_seeders=parse_seeders,
        compatibility_rank=lambda stream: (0,) if stream is compatible_weak else (2,),
    )

    assert ordered == [compatible_weak, incompatible_healthy]


def test_all_weak_torrents_remain_available_as_fallbacks() -> None:
    better = torrent("better", 2)
    weaker = torrent("weaker", 1)

    ordered = POLICY._apply_seed_policy(
        [better, weaker],
        prefer_direct_play=False,
        parse_seeders=parse_seeders,
        compatibility_rank=lambda stream: (0,),
    )

    assert ordered == [better, weaker]


def test_low_power_mode_overrides_force_transcode() -> None:
    original = {
        CONST.CONF_AUDIO_MODE: "force_transcode",
        CONST.CONF_LOW_POWER_STREAM_SERVER: True,
    }

    adjusted = POLICY.effective_playback_options(original)

    assert adjusted is not original
    assert adjusted[CONST.CONF_AUDIO_MODE] == "direct"
    assert original[CONST.CONF_AUDIO_MODE] == "force_transcode"


def test_normal_server_keeps_force_transcode() -> None:
    original = {
        CONST.CONF_AUDIO_MODE: "force_transcode",
        CONST.CONF_LOW_POWER_STREAM_SERVER: False,
    }

    assert POLICY.effective_playback_options(original) is original
