# ===============================
# src/napari_mmc_tools/_shared.py
# ===============================
from __future__ import annotations
from pymmcore_plus import CMMCorePlus

def core() -> CMMCorePlus:
    """Return the shared CMMCorePlus instance (same process as napari)."""
    return CMMCorePlus.instance()