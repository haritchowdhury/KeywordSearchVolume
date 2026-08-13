"""Config + secrets loading. All weights/thresholds live in config.yaml and .env."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict

import yaml
from dotenv import load_dotenv


class DotDict(dict):
    """Dict with attribute access that stays tolerant of missing keys."""

    def __getattr__(self, name: str) -> Any:  # type: ignore[override]
        try:
            value = self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc
        if isinstance(value, dict) and not isinstance(value, DotDict):
            value = DotDict(value)
            self[name] = value
        return value

    def __setattr__(self, name: str, value: Any) -> None:  # type: ignore[override]
        self[name] = value


@dataclass
class Credentials:
    login: str
    password: str

    @property
    def present(self) -> bool:
        return bool(self.login) and bool(self.password)


@dataclass
class Config:
    raw: DotDict = field(default_factory=DotDict)
    root: Path = field(default_factory=Path)
    creds: Credentials = field(default_factory=lambda: Credentials("", ""))

    # convenience accessors --------------------------------------------------
    @property
    def api(self) -> DotDict:
        return self.raw.api

    @property
    def scoring(self) -> DotDict:
        return self.raw.scoring

    @property
    def filters(self) -> DotDict:
        return self.raw.filters

    @property
    def clustering(self) -> DotDict:
        return self.raw.clustering

    @property
    def dedup(self) -> DotDict:
        return self.raw.dedup

    @property
    def intent(self) -> DotDict:
        return self.raw.intent

    @property
    def cache_cfg(self) -> DotDict:
        return self.raw.cache

    @property
    def paths(self) -> DotDict:
        return self.raw.paths

    @property
    def expansion(self) -> DotDict:
        return self.raw.expansion

    @property
    def endpoints(self) -> DotDict:
        return self.raw.endpoints

    @property
    def search(self) -> DotDict:
        return self.raw.search

    @property
    def run_cfg(self) -> DotDict:
        return self.raw.run

    def abs_path(self, relative: str) -> Path:
        return self.root / relative


def load_config(config_path: str | Path = "config.yaml",
                env_path: str | Path | None = None) -> Config:
    root = Path(config_path).resolve().parent
    if env_path is None:
        env_path = root / ".env"
    load_dotenv(env_path)

    with open(config_path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    cfg = Config(raw=DotDict(data), root=root,
                 creds=Credentials(login=os.getenv("DATAFORSEO_LOGIN", ""),
                                   password=os.getenv("DATAFORSEO_PASSWORD", "")))

    for rel in (cfg.paths.raw_dir, cfg.paths.normalized_dir, cfg.paths.output_dir):
        (root / rel).mkdir(parents=True, exist_ok=True)
    return cfg
