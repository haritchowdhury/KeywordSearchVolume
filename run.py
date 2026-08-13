"""Entry point: load config, build client + cache, run pipeline, print summary.

Usage:
    python3 run.py                 # uses seeds from config.yaml
    python3 run.py "pickleball" "yoga mat"   # override seeds
    DATAFORSEO_LOGIN=... DATAFORSEO_PASSWORD=... python3 run.py
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from pipeline.cache import ResponseCache
from pipeline.client import DataForSEOError, DataForSEOClient
from pipeline.config import load_config
from pipeline.pipeline import KeywordPipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Keyword intelligence pipeline")
    parser.add_argument("seeds", nargs="*", help="seed keywords (overrides config)")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--offline", action="store_true",
                        help="use bundled fixtures instead of the live API")
    parser.add_argument("--no-cache", action="store_true",
                        help="bypass the local response cache")
    parser.add_argument("--clear-cache", action="store_true",
                        help="clear the response cache before running")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    root = Path(args.config).resolve().parent
    config = load_config(args.config)
    if args.offline:
        config.run_cfg.offline_mode = True
    if args.no_cache:
        config.cache_cfg.enabled = False

    cache = ResponseCache(
        db_path=config.abs_path(config.cache_cfg.db_path),
        ttl_seconds=config.cache_cfg.ttl_seconds,
        enabled=config.cache_cfg.enabled,
    )
    if args.clear_cache:
        cache.clear()
        print("cache cleared")

    seeds = args.seeds or list(config.run_cfg.seeds)

    if config.run_cfg.offline_mode or not config.creds.present:
        from tests.fixtures import build_offline_client
        client = build_offline_client(config, cache)
    else:
        client = DataForSEOClient(config, cache)

        # quick auth probe so we fail fast with a clear message
        try:
            client.keyword_overview([seeds[0]]) if False else None
        except DataForSEOError as exc:
            print(f"ERROR: cannot reach DataForSEO: {exc}", file=sys.stderr)
            return 2

    pipeline = KeywordPipeline(config, client)
    try:
        result = pipeline.run(seeds)
    except DataForSEOError as exc:
        print(f"ERROR: pipeline aborted: {exc}", file=sys.stderr)
        return 3

    cluster_dicts = [c.to_dict() for c in result["cluster_objects"]]
    print("\n===== SUMMARY =====")
    print(f"seeds:                   {result['seeds']}")
    print(f"raw items collected:     {result['total_raw_items']}")
    print(f"items with metrics:      {result['with_metrics']}")
    print(f"informational dropped:   {result['informational_dropped']}")
    print(f"dedup-merged variants:   {result.get('dedup_merged', 0)}")
    print(f"active keywords:         {result['active_keywords']}")
    print(f"clusters:                {result['clusters']}")
    print(f"recommended clusters:    {result['recommended_clusters']}")
    print("\n--- top recommended clusters ---")
    top = sorted(cluster_dicts, key=lambda c: c["opportunity_score"], reverse=True)
    for c in top[:8]:
        print(f"  [{c['opportunity_score']:3d}] {'REC ' if c['recommended_for_store_discovery'] else '    '} "
              f"{c['cluster']}  (vol={c['combined_volume']}, cpc={c['avg_cpc']}, "
              f"ci={c['commercial_intent']}, trend={c['trend_score']})")
    print("\noutputs:")
    for k, v in result["outputs"].items():
        print(f"  {k}: {Path(v).relative_to(root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
