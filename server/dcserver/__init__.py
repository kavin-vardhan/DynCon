"""dcserver — the DynamicContents demo server (the stand-in cloud).

Timestamp-driven: no timers, no background threads, every rule evaluated from stored
timestamps when a request arrives, so the same code could run in a Lambda. Storage sits
behind two interfaces — `Repo` (SQLite here) and `Blobs` (the local file system here) —
so AWS mode is a config change.
"""
from .app import VERSION, create_app

__all__ = ["create_app", "VERSION"]
