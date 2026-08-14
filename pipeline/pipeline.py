"""Pipeline orchestration: expand -> fetch metrics -> normalize -> filter ->
dedup -> cluster -> score/flag -> emit JSON+CSV. Handles partial failures
per seed so one bad seed never aborts the whole run."""
from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from typing import Dict, List, Optional

from .client import DataForSEOClient
from .cluster import attach_variants, cluster_keywords
from .config import Config
from .dedup import dedup_variants
from .intent import is_informational
from .models import Cluster, KeywordRecord, MarketMetrics
from .normalize import compute_trend_slope, has_metrics, normalize_item
from .output import (write_clusters_csv, write_clusters_json,
                     write_keywords_csv, write_keywords_json,
                     write_market_json, write_markets_manifest)
from .score import score_all_clusters, score_and_flag_all

logger = logging.getLogger(__name__)

OVERVIEW_BATCH = 250  # endpoint accepts up to 1000; moderate batches reduce multi-market round trips


class KeywordPipeline:
    def __init__(self, config: Config, client: DataForSEOClient) -> None:
        self.config = config
        self.client = client

    # ------------------------------------------------------------------ #
    def _markets(self) -> List[dict]:
        configured = self.config.search.get("markets") or []
        if configured:
            return [dict(market) for market in configured]
        return [{
            "code": "US",
            "name": self.config.search.location_name,
            "location_code": 2840,
            "language_name": self.config.search.language_name,
        }]

    def _client_expand(self, seed: str, market: dict) -> List[str]:
        try:
            return self.client.expand(seed, market)
        except TypeError:  # compatibility with third-party single-market clients
            return self.client.expand(seed)

    def _client_overview(self, keywords: List[str], market: dict) -> List[dict]:
        try:
            return self.client.keyword_overview(keywords, market)
        except TypeError:  # compatibility with third-party single-market clients
            return self.client.keyword_overview(keywords)

    def _collect_for_seed(self, seed: str, market: Optional[dict] = None) -> List[KeywordRecord]:
        market = market or self._markets()[0]
        try:
            keywords = self._client_expand(seed, market)
        except Exception as exc:  # noqa: BLE001 - isolate per-seed failures
            logger.error("expansion failed for '%s': %s", seed, exc)
            keywords = [seed]

        records: List[KeywordRecord] = []
        for i in range(0, len(keywords), OVERVIEW_BATCH):
            batch = keywords[i:i + OVERVIEW_BATCH]
            raw_ref = None
            try:
                items = self._client_overview(batch, market)
            except Exception as exc:  # noqa: BLE001
                logger.error("overview failed for '%s' batch %d: %s", seed, i, exc)
                continue
            # capture raw_ref from the most recent call (same for the batch)
            for item in items:
                rec = normalize_item(item, seed=seed, raw_ref=raw_ref,
                                     config=self.config)
                if rec is not None:
                    records.append(rec)
        logger.info("market=%s seed='%s' collected=%d", market["code"], seed, len(records))
        return records

    @staticmethod
    def _market_metric(record: KeywordRecord, market: dict) -> MarketMetrics:
        return MarketMetrics(
            country_code=market["code"],
            location_code=int(market.get("location_code") or 0),
            location_name=market["name"],
            language_name=market.get("language_name", "English"),
            search_volume=record.search_volume,
            cpc=record.cpc,
            competition=record.competition,
            competition_level=record.competition_level,
            keyword_difficulty=record.keyword_difficulty,
            main_intent=record.main_intent,
            commercial_intent=record.commercial_intent,
            monthly_history=record.monthly_history,
            trend_slope=record.trend_slope,
        )

    @staticmethod
    def _weighted(metrics: List[MarketMetrics], field: str) -> Optional[float]:
        values = [(getattr(metric, field), metric.search_volume or 0) for metric in metrics
                  if getattr(metric, field) is not None]
        if not values:
            return None
        total_weight = sum(weight for _, weight in values)
        if total_weight <= 0:
            return sum(float(value) for value, _ in values) / len(values)
        return sum(float(value) * weight for value, weight in values) / total_weight

    def _apply_cumulative_metrics(self, record: KeywordRecord) -> None:
        metrics = list(record.market_metrics.values())
        record.search_volume = sum(metric.search_volume or 0 for metric in metrics)
        record.cpc = self._weighted(metrics, "cpc")
        record.competition = self._weighted(metrics, "competition")
        difficulty = self._weighted(metrics, "keyword_difficulty")
        record.keyword_difficulty = round(difficulty) if difficulty is not None else None
        commercial = self._weighted(metrics, "commercial_intent")
        record.commercial_intent = commercial if commercial is not None else 0.0
        intents = Counter()
        for metric in metrics:
            if metric.main_intent:
                intents[metric.main_intent] += metric.search_volume or 1
        record.main_intent = intents.most_common(1)[0][0] if intents else None
        history = defaultdict(int)
        for metric in metrics:
            for year, month, volume in metric.monthly_history:
                history[(year, month)] += volume or 0
        record.monthly_history = [
            (year, month, history[(year, month)]) for year, month in sorted(history)
        ]
        history_payload = [
            {"year": year, "month": month, "search_volume": volume}
            for year, month, volume in record.monthly_history
        ]
        record.trend_slope = compute_trend_slope(
            history_payload, self.config.filters.declining_periods
        )

    @staticmethod
    def _record_for_metric(record: KeywordRecord, metric: MarketMetrics) -> KeywordRecord:
        return KeywordRecord(
            keyword=record.keyword, seed=record.seed,
            search_volume=metric.search_volume, cpc=metric.cpc,
            competition=metric.competition,
            competition_level=metric.competition_level,
            keyword_difficulty=metric.keyword_difficulty,
            main_intent=metric.main_intent,
            monthly_history=metric.monthly_history,
            trend_slope=metric.trend_slope,
            commercial_intent=metric.commercial_intent,
            cluster_id=record.cluster_id, cluster_label=record.cluster_label,
            merged_into=record.merged_into, source_seeds=record.source_seeds,
            variant_group_id=record.variant_group_id,
            variant_canonical=record.variant_canonical,
            lane=record.lane, facets=record.facets,
            flags=list(metric.flags), opportunity_score=metric.opportunity_score,
            recommended=metric.recommended,
        )

    def _score_markets(self, records: List[KeywordRecord], markets: List[dict]) -> None:
        for market in markets:
            code = market["code"]
            pairs = [(record, record.market_metrics.get(code)) for record in records]
            pairs = [(record, metric) for record, metric in pairs if metric is not None]
            temp_records = [self._record_for_metric(record, metric) for record, metric in pairs]
            score_and_flag_all(temp_records, self.config, include_merged=True)
            for (_, metric), scored in zip(pairs, temp_records):
                metric.flags = scored.flags
                metric.opportunity_score = scored.opportunity_score
                metric.recommended = scored.recommended

    def _market_cluster_metrics(self, clusters: List[Cluster], code: str) -> Dict[str, dict]:
        market_clusters = []
        for cluster in clusters:
            members = []
            for record in cluster.records:
                metric = record.market_metrics.get(code)
                if metric is not None:
                    members.append(self._record_for_metric(record, metric))
            if members:
                market_clusters.append(Cluster(
                    label=cluster.label, records=members, cluster_id=cluster.cluster_id
                ))
        score_all_clusters(market_clusters, self.config)
        return {
            cluster.cluster_id: {
                "combined_volume": cluster.combined_volume,
                "headline_volume": cluster.headline_volume,
                "adjusted_cluster_volume": cluster.adjusted_cluster_volume,
                "raw_variant_volume": cluster.raw_variant_volume,
                "avg_cpc": round(cluster.avg_cpc, 2),
                "commercial_intent": round(cluster.avg_commercial_intent, 2),
                "trend_score": round(cluster.trend_score, 3),
                "opportunity_score": cluster.opportunity_score,
                "recommended_for_store_discovery": cluster.recommended,
            }
            for cluster in market_clusters
        }

    # ------------------------------------------------------------------ #
    def run(self, seeds: List[str]) -> Dict[str, object]:
        markets = self._markets()
        discovered: Dict[str, dict] = {}
        for market in markets:
            for seed in seeds:
                try:
                    keywords = self._client_expand(seed, market)
                except Exception as exc:  # noqa: BLE001
                    logger.error("expansion failed market=%s seed='%s': %s", market["code"], seed, exc)
                    keywords = [seed]
                for keyword in keywords:
                    key = keyword.strip().lower()
                    if not key:
                        continue
                    entry = discovered.setdefault(key, {"keyword": keyword.strip(), "seeds": set(), "markets": set()})
                    entry["seeds"].add(seed)
                    entry["markets"].add(market["code"])

        keyword_list = [entry["keyword"] for entry in discovered.values()]
        base_records: Dict[str, KeywordRecord] = {}
        market_item_counts = Counter()
        raw_items_collected = 0
        items_with_metrics = 0
        informational_dropped = 0
        for market in markets:
            logger.info("collecting overview metrics for %s (%d keywords)", market["name"], len(keyword_list))
            for i in range(0, len(keyword_list), OVERVIEW_BATCH):
                batch = keyword_list[i:i + OVERVIEW_BATCH]
                try:
                    items = self._client_overview(batch, market)
                except Exception as exc:  # noqa: BLE001
                    logger.error("overview failed market=%s batch=%d: %s", market["code"], i, exc)
                    continue
                raw_items_collected += len(items)
                for item in items:
                    key = str(item.get("keyword") or "").strip().lower()
                    source = discovered.get(key)
                    if not source:
                        continue
                    seed = sorted(source["seeds"])[0]
                    record = normalize_item(item, seed=seed, raw_ref=None, config=self.config)
                    if record is None or not has_metrics(record):
                        continue
                    items_with_metrics += 1
                    market_item_counts[market["code"]] += 1
                    if is_informational(record.keyword, record.main_intent, self.config):
                        informational_dropped += 1
                    base = base_records.get(key)
                    if base is None:
                        base = KeywordRecord(keyword=record.keyword, seed=seed,
                                             source_seeds=sorted(source["seeds"]))
                        base_records[key] = base
                    metric = self._market_metric(record, market)
                    current = base.market_metrics.get(market["code"])
                    if current is None or (metric.search_volume or 0) > (current.search_volume or 0):
                        base.market_metrics[market["code"]] = metric

        kept = list(base_records.values())
        missing_markets = [market["code"] for market in markets
                           if market_item_counts[market["code"]] == 0]
        if missing_markets:
            raise RuntimeError(
                "no usable overview metrics returned for market(s): "
                + ", ".join(missing_markets)
                + "; existing output files were left unchanged"
            )
        for record in kept:
            self._apply_cumulative_metrics(record)
        logger.info("unique phrases with metrics: %d across %d markets", len(kept), len(markets))

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
        # Score every distinct wording variant so the 3D map can plot all
        # points meaningfully. Summary/recommendation counts still use the
        # canonical active set to avoid cross-seed duplication.
        score_and_flag_all(deduped, self.config, include_merged=True)
        score_all_clusters(clusters, self.config)
        self._score_markets(deduped, markets)

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
            "markets_json": str(write_markets_manifest(
                markets, out_dir / "markets.json")),
        }

        for market in markets:
            code = market["code"]
            cluster_metrics = self._market_cluster_metrics(clusters, code)
            market_active = [record for record in active if code in record.market_metrics]
            market_summary = {
                "active_keywords": len(market_active),
                "recommended_keywords": sum(
                    1 for record in market_active if record.market_metrics[code].recommended
                ),
                "clusters": len(cluster_metrics),
                "recommended_clusters": sum(
                    1 for metric in cluster_metrics.values()
                    if metric["recommended_for_store_discovery"]
                ),
            }
            path = write_market_json(
                active + merged, market, cluster_metrics, market_summary,
                out_dir / "markets" / (code + ".json"),
            )
            written["market_" + code.lower() + "_json"] = str(path)

        summary_path = out_dir / "summary.json"
        with open(summary_path, "w", encoding="utf-8") as fh:
            json.dump({
                "schema_version": 3,
                "markets": markets,
                "seeds": seeds,
                "raw_items_collected": raw_items_collected,
                "items_with_metrics": items_with_metrics,
                "informational_dropped": informational_dropped,
                "unique_phrases": len(kept),
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
            "markets": markets,
            "total_raw_items": raw_items_collected,
            "with_metrics": items_with_metrics,
            "informational_dropped": informational_dropped,
            "dedup_merged": dedup_merged,
            "active_keywords": len(active),
            "clusters": len(clusters),
            "recommended_clusters": sum(1 for c in clusters if c.recommended),
            "outputs": written,
            "cluster_objects": clusters,
        }
