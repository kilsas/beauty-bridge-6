"""Beauty Bridge: explainable cross-market beauty product recommendation."""
from __future__ import annotations

from pathlib import Path

from .db import DEFAULT_DATA_DIR, Dataset, build_sqlite, load_folder, load_sqlite
from .engine import Engine, NotFound

__version__ = "0.1.0"


def load_engine(source: str | Path | None = None) -> Engine:
    """
    source: a data folder (CSV files), a .sqlite file, or None for the demo data.
    """
    if source is None:
        return Engine(load_folder(DEFAULT_DATA_DIR))
    source = Path(source)
    if source.suffix in {".sqlite", ".db"}:
        return Engine(load_sqlite(source))
    return Engine(load_folder(source))


__all__ = ["Engine", "Dataset", "NotFound", "load_engine", "load_folder",
           "build_sqlite", "load_sqlite", "__version__"]
