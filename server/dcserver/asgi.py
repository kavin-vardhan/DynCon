"""What uvicorn runs: `uvicorn dcserver.asgi:app --host 127.0.0.1 --port 8700`.

Paths can be pointed somewhere else with environment variables, which is how a second
instance (or a test run against a real socket) stays out of the way of the booth data:

    DCSERVER_CONFIG      path to demo.json          (default server/config/demo.json)
    DCSERVER_DATA        the data folder            (default server/data)
    DCSERVER_DEMO_FILES  "the brand's computer"     (default server/demo_files)
"""
from __future__ import annotations

import logging
import os

from .app import DEFAULT_CONFIG, create_app

logging.basicConfig(level=os.environ.get("DCSERVER_LOG", "INFO"),
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = create_app(
    os.environ.get("DCSERVER_CONFIG") or DEFAULT_CONFIG,
    data_dir=os.environ.get("DCSERVER_DATA") or None,
    demo_files=os.environ.get("DCSERVER_DEMO_FILES") or None,
)
