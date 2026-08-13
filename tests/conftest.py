"""Shared pytest fixtures."""
from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.config import load_config


@pytest.fixture(scope="session")
def cfg() -> object:
    root = Path(__file__).resolve().parent.parent
    return load_config(root / "config.yaml", env_path=root / ".env")


@pytest.fixture
def tmp_cfg(cfg) -> object:
    return cfg
