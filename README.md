# Keyword intelligence pipeline

Run `python3 run.py` to expand the configured seeds, collect keyword metrics,
organise wording variants, build non-transitive topic clusters, score the
opportunities, and write JSON/CSV files under `data/output`.

Cluster output keeps the legacy `combined_volume` field and adds:

- `headline_volume`: largest individual keyword volume
- `adjusted_cluster_volume`: conservative view with identical metric/history buckets counted once
- `raw_variant_volume`: primary cumulative volume across every distinct wording variant
- `variant_groups`, `source_seeds`, `lane_counts`, and extracted `facets`

`combined_volume` now mirrors cumulative distinct-phrase traffic. The dashboard
prefers the richer schema but falls back to legacy fields, so an
older output can still be opened during migration.
