import sys

import pytest

from dictado.backends import (
    BACKEND_CPU,
    BACKEND_CUDA,
    BACKEND_MLX,
    mlx_importable,
    select_backend,
)
from dictado.config import Config


@pytest.fixture
def fake_spec():
    """`find_spec_fn` factory: mlx_whisper importable only when allowed."""
    holder = {"mlx": True}

    def factory(name):
        if holder["mlx"] and name == "mlx_whisper":
            return object()
        return None

    holder["find"] = factory
    yield holder


def test_darwin_arm64_with_mlx_picks_mlx(fake_spec) -> None:
    config = Config(device="auto")
    assert (
        select_backend(
            config,
            platform_name="darwin",
            machine="arm64",
            find_spec_fn=fake_spec["find"],
        )
        == BACKEND_MLX
    )


def test_darwin_arm64_without_mlx_falls_to_cpu(fake_spec) -> None:
    fake_spec["mlx"] = False
    config = Config(device="auto")
    assert (
        select_backend(
            config,
            platform_name="darwin",
            machine="arm64",
            find_spec_fn=fake_spec["find"],
        )
        == BACKEND_CPU
    )


def test_darwin_intel_is_never_mlx(fake_spec) -> None:
    config = Config(device="auto")
    assert (
        select_backend(
            config,
            platform_name="darwin",
            machine="x86_64",
            find_spec_fn=fake_spec["find"],
        )
        == BACKEND_CPU
    )


def test_darwin_device_cpu_skips_mlx(fake_spec) -> None:
    config = Config(device="cpu")
    assert (
        select_backend(
            config,
            platform_name="darwin",
            machine="arm64",
            find_spec_fn=fake_spec["find"],
        )
        == BACKEND_CPU
    )


def test_darwin_device_mlx_is_explicit_and_honored(fake_spec) -> None:
    config = Config(device="mlx")
    assert (
        select_backend(
            config,
            platform_name="darwin",
            machine="arm64",
            find_spec_fn=fake_spec["find"],
        )
        == BACKEND_MLX
    )
    # ... and still falls back to CPU when mlx is missing
    fake_spec["mlx"] = False
    assert (
        select_backend(
            config,
            platform_name="darwin",
            machine="arm64",
            find_spec_fn=fake_spec["find"],
        )
        == BACKEND_CPU
    )


def test_windows_with_cuda_keeps_current_behaviour() -> None:
    config = Config(device="auto")
    assert (
        select_backend(
            config,
            platform_name="win32",
            machine="AMD64",
            find_spec_fn=lambda _name: None,
            cuda_ok=True,
        )
        == BACKEND_CUDA
    )
    assert (
        select_backend(
            config,
            platform_name="win32",
            machine="AMD64",
            find_spec_fn=lambda _name: None,
            cuda_ok=False,
        )
        == BACKEND_CPU
    )


def test_windows_device_cpu_ignores_cuda() -> None:
    assert (
        select_backend(
            Config(device="cpu"),
            platform_name="win32",
            machine="AMD64",
            find_spec_fn=lambda _name: None,
            cuda_ok=True,
        )
        == BACKEND_CPU
    )


def test_windows_device_cuda_without_gpu_falls_to_cpu() -> None:
    assert (
        select_backend(
            Config(device="cuda"),
            platform_name="win32",
            machine="AMD64",
            find_spec_fn=lambda _name: None,
            cuda_ok=False,
        )
        == BACKEND_CPU
    )


def test_other_linux_treats_mlx_as_absent() -> None:
    assert (
        select_backend(
            Config(device="mlx"),
            platform_name="linux",
            machine="x86_64",
            find_spec_fn=lambda name: object() if name == "mlx_whisper" else None,
            cuda_ok=False,
        )
        == BACKEND_CPU
    )


def test_mlx_importable_only_on_darwin() -> None:
    # Never probes the real filesystem off-darwin: the platform flag wins.
    if sys.platform == "darwin":
        pytest.skip("the helper legitimately answers True on a real darwin machine")
    assert mlx_importable("darwin", lambda _name: None) is False
    assert mlx_importable("win32", lambda _name: object()) is False


def test_backend_default_probes_real_platform() -> None:
    """With no overrides, select_backend answers without raising."""
    assert select_backend(Config(device="cpu")) == BACKEND_CPU