# Keyword intelligence pipeline

Run `python3 run.py` to expand the configured seeds, collect keyword metrics,
organise wording variants, build non-transitive topic clusters, score the
opportunities, and write JSON/CSV files under `data/output`.

The default run collects the nine country markets configured under `search.markets`.
Use `python3 run.py --markets US,GB,IN` to refresh only selected markets. The
dashboard opens on the cumulative view and lazily loads country files from
`data/output/markets/` when the Market filter changes. Germany and France use
the German and French DataForSEO Labs databases; the other configured markets
use English.

Cluster output keeps the legacy `combined_volume` field and adds:

- `headline_volume`: largest individual keyword volume
- `adjusted_cluster_volume`: conservative view with identical metric/history buckets counted once
- `raw_variant_volume`: primary cumulative volume across every distinct wording variant
- `variant_groups`, `source_seeds`, `lane_counts`, and extracted `facets`

`combined_volume` now mirrors cumulative distinct-phrase traffic. The dashboard
prefers the richer schema but falls back to legacy fields, so an
older output can still be opened during migration.

Schema version 3 adds `markets.json` and one file per country. Search volume,
monthly history, CPC, competition, flags, opportunity scores, and recommendations
are calculated independently per market. Top-level keyword and cluster metrics
remain the cumulative totals across all configured countries.
