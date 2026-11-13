import pytest

from openlocate.engine.geo import LatLon, haversine_m
from openlocate.engine.jitter import Jitter, JitterConfig

POINT = LatLon(51.5, -0.12)


def test_speed_factor_stays_within_bounds_and_moves() -> None:
    config = JitterConfig(speed_fraction=0.05)
    jitter = Jitter(config, seed=1)
    factors = [jitter.speed_factor() for _ in range(10_000)]
    assert all(0.95 <= f <= 1.05 for f in factors)
    assert len(set(factors)) > 100


def test_speed_factor_drifts_smoothly() -> None:
    jitter = Jitter(JitterConfig(speed_fraction=0.05), seed=2)
    factors = [jitter.speed_factor() for _ in range(10_000)]
    biggest_jump = max(abs(b - a) for a, b in zip(factors[:-1], factors[1:], strict=True))
    # One step can change the factor by at most (1 - smoothing) * 2 * fraction.
    assert biggest_jump <= 0.1 * 2 * 0.05 + 1e-12


def test_offset_never_exceeds_twice_position_m() -> None:
    jitter = Jitter(JitterConfig(position_m=1.5), seed=3)
    distances = [haversine_m(POINT, jitter.offset(POINT)) for _ in range(10_000)]
    assert max(distances) <= 3.0 + 1e-6
    assert max(distances) > 1.0  # it does move


def test_same_seed_same_sequence() -> None:
    def sample(seed: int) -> list[object]:
        jitter = Jitter(JitterConfig(), seed=seed)
        return [(jitter.speed_factor(), jitter.offset(POINT)) for _ in range(100)]

    assert sample(42) == sample(42)
    assert sample(42) != sample(43)


def test_disabled_is_exact() -> None:
    jitter = Jitter(JitterConfig(enabled=False), seed=4)
    for _ in range(100):
        assert jitter.speed_factor() == 1.0
        assert jitter.offset(POINT) is POINT


@pytest.mark.parametrize(
    "kwargs", [{"speed_fraction": -0.1}, {"speed_fraction": 1.0}, {"position_m": -1.0}]
)
def test_invalid_config(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        JitterConfig(**kwargs)  # type: ignore[arg-type]
