"""Tests for runtime dependencies the generator needs but does not declare."""

import importlib


def test_litellm_retry_dependency_is_installed() -> None:
    """LiteLLM needs tenacity for the generator's ``num_retries``.

    Neither litellm 1.110 nor the generator 0.2.0 declare it; without it
    every AI request fails with "tenacity import failed".
    """
    assert importlib.import_module("tenacity")
