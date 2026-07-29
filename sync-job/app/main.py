"""Unused entrypoint stub — superseded by sync_job/main.py.

The real sync pipeline (Document360 -> chunk -> embed -> Vector Search) is
implemented in sync_job/main.py, which is what the Dockerfile actually runs.
"""

from __future__ import annotations

import sys

import structlog

log = structlog.get_logger()


def main() -> int:
    log.info("sync_job_started")
    log.info("sync_job_completed", articles_processed=0, chunks_upserted=0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
