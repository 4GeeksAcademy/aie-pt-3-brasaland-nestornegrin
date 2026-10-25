# `data/raw` folder

This folder is intended for **raw data** related to the company: dumps, exports, sample files, event samples, or untransformed datasets.

- **Main purpose**: serve as a landing zone or reference for original data before pipelines process it.
- **Recommendation**: document each dataset’s origin, format, expected size, privacy/PII considerations, and how it is versioned (ideally avoiding sensitive data in the repository).

## `brasaland_sales.csv`

Course-provided dataset (never generated or modified): monthly consolidated sales of the 14 locations, 120 rows from
2016-01 to 2025-12 (`market = consolidated`). Columns: `month`, `revenue_usd`, `covers_served`, `avg_ticket_usd`,
`market`. Used by the sales forecast model (`scripts/sales_forecast/`); its SHA-256 is recorded in
`data/eval/sales_forecast/metrics.json`. No personal data.

> _Spanish version: [README.es.md](./README.es.md)._
