"""Tests for runtime dependencies that every AI request needs."""

import importlib


def test_litellm_retry_dependency_is_installed() -> None:
    """LiteLLM needs tenacity for the generator's ``num_retries``.

    LiteLLM does not declare it; the generator does since 0.2.1. Without it
    every AI request fails with "tenacity import failed".
    """
    assert importlib.import_module("tenacity")
