# `data/raw` folder

This folder is intended for **raw data** related to the company: dumps, exports, sample files, event samples, or untransformed datasets.

- **Main purpose**: serve as a landing zone or reference for original data before pipelines process it.
- **Recommendation**: document each dataset’s origin, format, expected size, privacy/PII considerations, and how it is versioned (ideally avoiding sensitive data in the repository).

> _Spanish version: [README.es.md](./README.es.md)._

- **Nightly telemetry backup:** `telemetry_YYYY-MM-DD.csv` is written by `scripts/nightly_export.py` (backup/audit of the previous day; the pipeline does NOT read it). It is git-ignored: it holds user data.
