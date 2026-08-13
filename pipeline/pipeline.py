"""Pipeline orchestration: expand -> fetch metrics -> normalize -> filter ->
dedup -> cluster -> score/flag -> emit JSON+CSV. Handles partial failures
per seed so one bad seed never aborts the whole run."""
from __future__ import annotations

import json
import logging
from typing import Dict, List

from .client import DataForSEOClient
from .cluster import attach_variants, cluster_keywords
from .config import Config
from .dedup import dedup_variants
from .intent import is_informational
from .models import Cluster, KeywordRecord
from .normalize import has_metrics, normalize_item
from .output import (write_clusters_csv, write_clusters_json,
                     write_keywords_csv, write_keywords_json)
from .score import score_all_clusters, score_and_flag_all

logger = logging.getLogger(__name__)

OVERVIEW_BATCH = 25  # keyword_overview accepts up to 1000; batch keeps calls cheap & resilient


class KeywordPipeline:
    def __init__(self, config: Config, client: DataForSEOClient) -> None:
        self.config = config
        self.client = client

    # ------------------------------------------------------------------ #
    def _collect_for_seed(self, seed: str) -> List[KeywordRecord]:
        try:
            keywords = self.client.expand(seed)
        except Exception as exc:  # noqa: BLE001 - isolate per-seed failures
            logger.error("expansion failed for '%s': %s", seed, exc)
            keywords = [seed]

        records: List[KeywordRecord] = []
        for i in range(0, len(keywords), OVERVIEW_BATCH):
            batch = keywords[i:i + OVERVIEW_BATCH]
            raw_ref = None
            try:
                items = self.client.keyword_overview(batch)
            except Exception as exc:  # noqa: BLE001
                logger.error("overview failed for '%s' batch %d: %s", seed, i, exc)
                continue
            # capture raw_ref from the most recent call (same for the batch)
            for item in items:
                rec = normalize_item(item, seed=seed, raw_ref=raw_ref,
                                     config=self.config)
                if rec is not None:
                    records.append(rec)
        logger.info("seed='%s' collected=%d", seed, len(records))
        return records

    # ------------------------------------------------------------------ #
    def run(self, seeds: List[str]) -> Dict[str, object]:
        all_records: List[KeywordRecord] = []
        for seed in seeds:
            all_records.extend(self._collect_for_seed(seed))

        # keep only rows that actually carry metrics
        with_metrics = [r for r in all_records if has_metrics(r)]
        logger.info("records with metrics: %d / %d", len(with_metrics), len(all_records))

        # drop irrelevant informational keywords
        kept: List[KeywordRecord] = []
        informational_dropped = 0
        for r in with_metrics:
            if is_informational(r.keyword, r.main_intent, self.config):
                r.flags.append("informational_dropped")
                informational_dropped += 1
                continue
            kept.append(r)

        # Preserve every expansion path before deduplication chooses one
        # canonical record. A keyword can legitimately be discovered by many
        # broad seeds and that provenance is useful in the dashboard.
        seeds_by_keyword: Dict[str, set] = {}
        for record in kept:
            seeds_by_keyword.setdefault(record.keyword.strip().lower(), set()).add(record.seed)
        for record in kept:
            record.source_seeds = sorted(seeds_by_keyword[record.keyword.strip().lower()])

        # dedup close variants
        deduped = dedup_variants(kept, self.config)
        active = [r for r in deduped if r.is_active]
        # preserve dropped/merged records in output for traceability
        merged = [r for r in deduped if not r.is_active]
        dedup_merged = len(merged)

        # Classify lanes/facets and cluster before recommendation so branded
        # competitor demand can remain visible without being recommended as an
        # unbranded store-discovery target.
        clusters = cluster_keywords(active, self.config)
        attach_variants(clusters, deduped)
        score_and_flag_all(active, self.config)
        score_all_clusters(clusters, self.config)

        # write outputs
        out_dir = self.config.abs_path(self.config.paths.output_dir)
        written = {
            "clusters_json": str(write_clusters_json(
                clusters, out_dir / "clusters.json")),
            "clusters_csv": str(write_clusters_csv(
                clusters, out_dir / "clusters.csv")),
            "keywords_json": str(write_keywords_json(
                active + merged, out_dir / "keywords.json")),
            "keywords_csv": str(write_keywords_csv(
                active + merged, out_dir / "keywords.csv")),
        }

        summary_path = out_dir / "summary.json"
        with open(summary_path, "w", encoding="utf-8") as fh:
            json.dump({
                "schema_version": 2,
                "seeds": seeds,
                "raw_items_collected": len(all_records),
                "items_with_metrics": len(with_metrics),
                "informational_dropped": informational_dropped,
                "unique_phrases": len({r.keyword.strip().lower() for r in kept}),
                "dedup_merged": dedup_merged,
                "active_keywords": len(active),
                "variant_groups": sum(len(c.variant_groups) for c in clusters),
                "clusters": len(clusters),
                "recommended_keywords": sum(1 for r in active if r.recommended),
                "recommended_clusters": sum(1 for c in clusters if c.recommended),
            }, fh, ensure_ascii=False, indent=2)
        written["summary_json"] = str(summary_path)

        return {
            "seeds": seeds,
            "total_raw_items": len(all_records),
            "with_metrics": len(with_metrics),
            "informational_dropped": informational_dropped,
            "dedup_merged": dedup_merged,
            "active_keywords": len(active),
            "clusters": len(clusters),
            "recommended_clusters": sum(1 for c in clusters if c.recommended),
            "outputs": written,
            "cluster_objects": clusters,
        }
