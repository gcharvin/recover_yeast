# ===============================
# File tree
# ===============================
# napari-mmc-tools/
# ├─ pyproject.toml
# ├─ npe2.yaml
# └─ src/
#    └─ napari_mmc_tools/
#       ├─ __init__.py
#       ├─ _shared.py
#       ├─ tl_launcher.py
#       └─ positions_editor.py

# ===============================
# pyproject.toml
# ===============================
[build-system]
requires = ["setuptools>=61", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "napari-mmc-tools"
version = "0.1.0"
description = "Custom tools for napari-micromanager: shared TL launcher and MDA positions editor"
authors = [{name = "Your Name", email = "you@example.com"}]
readme = "README.md"
requires-python = ">=3.9"
dependencies = [
  "napari>=0.4.19",
  "magicgui>=0.7",
  "pymmcore-plus>=0.11",
  "useq-schema>=0.5",
  "PyYAML>=6",
]

[project.urls]
Homepage = "https://example.com/napari-mmc-tools"

[tool.setuptools]
package-dir = {"" = "src"}

# ===============================
# npe2.yaml
# ===============================
name: napari-mmc-tools
display_name: MMC Tools
contributions:
  commands:
    - id: napari-mmc-tools.tl_launcher
      title: Shared TL Launcher
      python_name: napari_mmc_tools.tl_launcher:widget
    - id: napari-mmc-tools.positions_editor
      title: MDA Positions Editor
      python_name: napari_mmc_tools.positions_editor:widget
  widgets:
    - command: napari-mmc-tools.tl_launcher
      display_name: Shared TL Launcher
    - command: napari-mmc-tools.positions_editor
      display_name: MDA Positions Editor

# ===============================
# src/napari_mmc_tools/__init__.py
# ===============================
from .tl_launcher import widget as TLLauncher  # noqa: F401
from .positions_editor import widget as PositionsEditor  # noqa: F401

__all__ = ["TLLauncher", "PositionsEditor"]

# ===============================
# src/napari_mmc_tools/_shared.py
# ===============================
from __future__ import annotations
from pymmcore_plus import CMMCorePlus

def core() -> CMMCorePlus:
    """Return the shared CMMCorePlus instance (same process as napari)."""
    return CMMCorePlus.instance()

# ===============================
# src/napari_mmc_tools/tl_launcher.py
# ===============================
from __future__ import annotations
from pathlib import Path
from typing import Optional

from magicgui import magicgui
from magicgui.widgets import Container, FileEdit, PushButton, Label, ComboBox
from qtpy.QtWidgets import QMessageBox
import useq

from ._shared import core


def widget():
    c = core()

    status = Label(value="Load a useq file or build a simple TL from a Channel preset.")
    file = FileEdit(mode="r", label="Sequence (*.useq.json|*.yaml)")
    btn_load = PushButton(label="📂 Load sequence")
    btn_start = PushButton(label="▶️ Start TL")
    btn_stop = PushButton(label="⏹ Stop")

    try:
        ch_presets = list(c.getAvailableConfigs("Channel")) or ["(none)"]
    except Exception:
        ch_presets = ["(none)"]
    channel = ComboBox(label="Channel preset", choices=ch_presets)
    btn_build = PushButton(label="🧱 Build simple TL (5s × 60)")

    seq: Optional[useq.MDASequence] = None
    seq_path: Optional[Path] = None

    def on_load():
        nonlocal seq, seq_path
        path = Path(str(file.value))
        if not path.exists():
            QMessageBox.warning(None, "TL", f"File not found: {path}")
            return
        try:
            seq = useq.MDASequence.from_file(path)
            seq_path = path
            status.value = f"Loaded: {path.name}"
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(None, "TL", f"Cannot read sequence: {e}")

    def on_build():
        nonlocal seq, seq_path
        ch = channel.value
        if not ch or ch == "(none)":
            QMessageBox.information(None, "TL", "No Channel preset available.")
            return
        try:
            expo = float(c.getExposure())
        except Exception:
            expo = 20.0
        seq = useq.MDASequence(
            time_plan=useq.TimePlan(interval=5.0, loops=60),
            channels=[useq.Channel(config=ch, exposure=expo)],
        )
        seq_path = None
        status.value = f"Built simple TL (Channel={ch}, Expo={expo} ms)."

    def on_start():
        if c.mda.is_running():
            QMessageBox.information(None, "TL", "An acquisition is already running.")
            return
        if seq is None:
            QMessageBox.information(None, "TL", "Load or build a sequence first.")
            return
        try:
            c.mda.run(seq)
            status.value = "Starting time‑lapse…"
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(None, "TL", f"Failed to start MDA: {e}")

    def on_stop():
        try:
            if c.mda.is_running():
                c.mda.cancel()
        except Exception:
            pass

    btn_load.changed.connect(on_load)
    btn_build.changed.connect(on_build)
    btn_start.changed.connect(on_start)
    btn_stop.changed.connect(on_stop)

    ui = Container(widgets=[
        status,
        Container(widgets=[file, btn_load], layout='horizontal'),
        Container(widgets=[channel, btn_build], layout='horizontal'),
        Container(widgets=[btn_start, btn_stop], layout='horizontal'),
    ])

    return ui

# ===============================
# src/napari_mmc_tools/positions_editor.py
# ===============================
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
from magicgui.widgets import (
    Container,
    PushButton,
    LineEdit,
    ComboBox,
    Table,
    Label,
    FileEdit,
)
from qtpy.QtWidgets import QMessageBox, QFileDialog
from useq import MDASequence, Position

from ._shared import core


@dataclass
class PosRow:
    name: str
    x: float
    y: float
    z: float | None = None

    def to_useq(self) -> Position:
        kw = {"x": float(self.x), "y": float(self.y)}
        if self.z is not None:
            kw["z"] = float(self.z)
        return Position(name=self.name, **kw)


def _read_sequence(path: Path) -> MDASequence:
    return MDASequence.from_file(path)


def _write_sequence(path: Path, seq: MDASequence):
    seq.to_file(path)


def widget():
    c = core()

    file_edit = FileEdit(mode="r", label="Sequence (*.useq.json|*.yaml)")
    load_btn = PushButton(label="📂 Load sequence")
    name_edit = LineEdit(value="Pos1", label="Name")
    add_current_btn = PushButton(label="➕ Add current stage pos")
    add_points_btn = PushButton(label="➕ Import from Points layer")
    points_layer = ComboBox(choices=["(none)"])
    goto_btn = PushButton(label="🎯 Go to selected")
    update_from_stage_btn = PushButton(label="⬅️ Update from stage")
    save_btn = PushButton(label="💾 Save")
    save_as_btn = PushButton(label="💾 Save As…")
    status = Label(value="Load a sequence to start.")

    table = Table(value=[], headers=["Name","X","Y","Z"], label="Positions (double‑click to edit)")

    seq: Optional[MDASequence] = None
    seq_path: Optional[Path] = None
    rows: list[PosRow] = []

    def refresh_points_layers(*_):
        from napari.utils.notifications import show_info
        try:
            import napari
            v = napari.current_viewer()
            names = [lyr.name for lyr in v.layers if lyr.__class__.__name__ == "Points"]
        except Exception:
            names = []
        points_layer.choices = names or ["(none)"]

    def set_status(text: str):
        status.value = text

    def write_table():
        table.value = [[r.name, r.x, r.y, r.z if r.z is not None else ""] for r in rows]

    def read_table() -> list[PosRow]:
        out: list[PosRow] = []
        for r in table.value:
            name, x, y, z = r
            zval = float(z) if z not in (None, "", np.nan) else None
            out.append(PosRow(str(name), float(x), float(y), zval))
        return out

    def on_load():
        nonlocal seq, seq_path, rows
        path = Path(str(file_edit.value))
        if not path.exists():
            QMessageBox.warning(None, "Positions", f"File not found: {path}")
            return
        try:
            seq = _read_sequence(path)
            seq_path = path
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(None, "Positions", f"Failed to read: {e}")
            return
        rows = []
        if seq.stage_positions:
            for p in seq.stage_positions:
                if hasattr(p, "x"):
                    rows.append(PosRow(name=getattr(p, "name", ""), x=p.x, y=p.y, z=getattr(p, "z", None)))
                else:
                    x, y = p[:2]
                    z = p[2] if len(p) > 2 else None
                    rows.append(PosRow(name="", x=x, y=y, z=z))
        write_table()
        set_status(f"Loaded: {path.name}")
        refresh_points_layers()

    def on_add_current():
        try:
            x, y = c.getXYPosition()
        except Exception as e:
            QMessageBox.warning(None, "Positions", f"Cannot read XY: {e}")
            return
        zval = None
        try:
            zdev = c.getFocusDevice()
            if zdev:
                zval = float(c.getPosition())
        except Exception:
            zval = None
        name = name_edit.value or f"Pos{len(rows)+1}"
        rows.append(PosRow(name=name, x=float(x), y=float(y), z=zval))
        write_table()

    def on_add_from_points():
        import napari
        lname = points_layer.value
        if not lname or lname == "(none)":
            QMessageBox.information(None, "Positions", "No Points layer selected.")
            return
        v = napari.current_viewer()
        pts = v.layers[lname]
        if pts.__class__.__name__ != "Points":
            QMessageBox.information(None, "Positions", "Selected layer is not Points.")
            return
        coords = np.asarray(pts.data)
        for i, ccoords in enumerate(coords):
            if ccoords.shape[0] == 2:
                y, x = ccoords
                z = None
            else:
                z, y, x = ccoords[-3], ccoords[-2], ccoords[-1]
            rows.append(PosRow(name=f"Pt{i+1}", x=float(x), y=float(y), z=float(z) if z is not None else None))
        write_table()

    def on_goto():
        idx = table.current_index
        if idx is None or idx < 0 or idx >= len(rows):
            return
        r = read_table()[idx]
        try:
            c.setXYPosition(r.x, r.y)
            if r.z is not None:
                try:
                    c.setPosition(float(r.z))
                except Exception:
                    pass
        except Exception as e:
            QMessageBox.warning(None, "Positions", f"Cannot move stage: {e}")

    def on_update_from_stage():
        idx = table.current_index
        if idx is None or idx < 0:
            return
        try:
            x, y = c.getXYPosition()
            try:
                zdev = c.getFocusDevice()
                zval = float(c.getPosition()) if zdev else None
            except Exception:
                zval = None
            rows[idx].x = float(x)
            rows[idx].y = float(y)
            rows[idx].z = zval
            write_table()
        except Exception as e:
            QMessageBox.warning(None, "Positions", f"Cannot read stage: {e}")

    def build_updated_sequence() -> Optional[MDASequence]:
        nonlocal seq
        if seq is None:
            QMessageBox.information(None, "Positions", "Load a sequence first.")
            return None
        new_rows = read_table()
        positions = [r.to_useq() for r in new_rows]
        return MDASequence(**{**seq.model_dump(), "stage_positions": positions})

    def on_save():
        nonlocal seq
        if seq_path is None:
            on_save_as()
            return
        new_seq = build_updated_sequence()
        if new_seq is None:
            return
        try:
            _write_sequence(seq_path, new_seq)
            set_status(f"Saved: {seq_path.name}")
            seq = new_seq
        except Exception as e:
            QMessageBox.critical(None, "Positions", f"Save failed: {e}")

    def on_save_as():
        nonlocal seq_path, seq
        new_seq = build_updated_sequence()
        if new_seq is None:
            return
        dlg = QFileDialog()
        dlg.setAcceptMode(QFileDialog.AcceptSave)
        dlg.setNameFilters(["useq JSON (*.useq.json)", "YAML (*.useq.yaml)", "JSON (*.json)", "YAML (*.yaml)"])
        if dlg.exec_():
            out = Path(dlg.selectedFiles()[0])
            try:
                _write_sequence(out, new_seq)
                set_status(f"Saved: {out.name}")
                seq_path = out
                seq = new_seq
            except Exception as e:
                QMessageBox.critical(None, "Positions", f"Save failed: {e}")

    load_btn.changed.connect(on_load)
    add_current_btn.changed.connect(on_add_current)
    add_points_btn.changed.connect(on_add_from_points)
    goto_btn.changed.connect(on_goto)
    update_from_stage_btn.changed.connect(on_update_from_stage)
    save_btn.changed.connect(on_save)
    save_as_btn.changed.connect(on_save_as)

    ui = Container(widgets=[
        Container(widgets=[file_edit, load_btn], layout="horizontal"),
        status,
        table,
        Container(widgets=[name_edit, add_current_btn], layout="horizontal"),
        Container(widgets=[Label(value="Points layer:"), points_layer, add_points_btn], layout="horizontal"),
        Container(widgets=[goto_btn, update_from_stage_btn], layout="horizontal"),
        Container(widgets=[save_btn, save_as_btn], layout="horizontal"),
    ], layout="vertical")

    return ui
