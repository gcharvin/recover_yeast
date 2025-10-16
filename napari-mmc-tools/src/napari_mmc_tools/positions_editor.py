from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
from magicgui.widgets import ComboBox, Container, FileEdit, Label, LineEdit, PushButton, Table
from qtpy.QtWidgets import QFileDialog, QMessageBox
from useq import MDASequence, Position

from ._shared import core


@dataclass
class PosRow:
    name: str
    x: float
    y: float
    z: float | None = None

    def to_useq(self) -> Position:
        kwargs: dict[str, float] = {"x": float(self.x), "y": float(self.y)}
        if self.z is not None:
            kwargs["z"] = float(self.z)
        return Position(name=self.name, **kwargs)


def _read_sequence(path: Path) -> MDASequence:
    return MDASequence.from_file(path)


def _write_sequence(path: Path, seq: MDASequence) -> None:
    lower_name = path.name.lower()
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"} or lower_name.endswith(".useq.yaml"):
        try:
            import yaml  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("PyYAML is required to save YAML sequences.") from exc
        data = seq.model_dump(mode="python")
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        return

    path.write_text(seq.model_dump_json(indent=2), encoding="utf-8")


def widget() -> Container:
    c = core()

    file_edit = FileEdit(mode="r", label="Sequence (*.useq.json | *.useq.yaml | *.json | *.yaml)")
    load_btn = PushButton(label="Load sequence")
    name_edit = LineEdit(value="Pos1", label="Name")
    add_current_btn = PushButton(label="Add current stage pos")
    add_points_btn = PushButton(label="Import from Points layer")
    points_layer = ComboBox(choices=["(none)"])
    goto_btn = PushButton(label="Go to selected")
    update_from_stage_btn = PushButton(label="Update from stage")
    save_btn = PushButton(label="Save")
    save_as_btn = PushButton(label="Save As…")
    status = Label(value="Load a sequence to start.")

    table = Table(value=[], columns=["Name", "X", "Y", "Z"], label="Positions (double-click to edit)")

    seq: Optional[MDASequence] = None
    seq_path: Optional[Path] = None
    rows: list[PosRow] = []

    def refresh_points_layers() -> None:
        try:
            import napari

            viewer = napari.current_viewer()
            names = [layer.name for layer in viewer.layers if layer.__class__.__name__ == "Points"]
        except Exception:
            names = []
        points_layer.choices = names or ["(none)"]

    def set_status(text: str) -> None:
        status.value = text

    def write_table() -> None:
        table.value = [[r.name, r.x, r.y, r.z if r.z is not None else ""] for r in rows]

    def read_table() -> list[PosRow]:
        updated: list[PosRow] = []
        for name, x, y, z in table.value:
            zval = None
            if z not in (None, "", np.nan):
                try:
                    zval = float(z)
                except (TypeError, ValueError):
                    zval = None
            updated.append(PosRow(str(name), float(x), float(y), zval))
        return updated

    def on_load() -> None:
        nonlocal seq, seq_path, rows
        value = file_edit.value
        if not value:
            QMessageBox.warning(None, "Positions", "Select a sequence file first.")
            return
        path = Path(value).expanduser()
        if not path.exists():
            QMessageBox.warning(None, "Positions", f"File not found: {path}")
            return
        try:
            seq = _read_sequence(path)
            seq_path = path
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(None, "Positions", f"Failed to read sequence:\n{exc}")
            return

        rows = []
        if seq.stage_positions:
            for pos in seq.stage_positions:
                if isinstance(pos, Position):
                    rows.append(PosRow(name=pos.name or "", x=pos.x, y=pos.y, z=pos.z))
                else:
                    coords = np.asarray(pos)
                    x_val = float(coords[-1])
                    y_val = float(coords[-2]) if coords.size > 1 else 0.0
                    z_val = float(coords[-3]) if coords.size > 2 else None
                    rows.append(PosRow(name="", x=x_val, y=y_val, z=z_val))

        write_table()
        set_status(f"Loaded: {path.name}")
        refresh_points_layers()

    def on_add_current() -> None:
        try:
            x_pos, y_pos = c.getXYPosition()
        except Exception as exc:
            QMessageBox.warning(None, "Positions", f"Cannot read XY position:\n{exc}")
            return

        z_value = None
        try:
            focus_device = c.getFocusDevice()
            if focus_device:
                z_value = float(c.getPosition())
        except Exception:
            z_value = None

        name = name_edit.value or f"Pos{len(rows) + 1}"
        rows.append(PosRow(name=name, x=float(x_pos), y=float(y_pos), z=z_value))
        write_table()

    def on_add_from_points() -> None:
        try:
            import napari
        except ImportError:
            QMessageBox.information(None, "Positions", "napari is not available in this environment.")
            return

        lname = points_layer.value
        if not lname or lname == "(none)":
            QMessageBox.information(None, "Positions", "Select a Points layer first.")
            return

        viewer = napari.current_viewer()
        layer = viewer.layers.get(lname)
        if layer is None or layer.__class__.__name__ != "Points":
            QMessageBox.information(None, "Positions", "Selected layer is not a Points layer.")
            return

        coords = np.asarray(layer.data)
        for index, coord in enumerate(coords, start=1):
            if coord.shape[0] == 2:
                y_val, x_val = coord
                z_val = None
            else:
                z_val, y_val, x_val = coord[-3], coord[-2], coord[-1]
            rows.append(
                PosRow(
                    name=f"Pt{index}",
                    x=float(x_val),
                    y=float(y_val),
                    z=float(z_val) if z_val is not None else None,
                )
            )
        write_table()

    def on_goto() -> None:
        idx = getattr(table, "current_index", None)
        if idx is None or idx < 0:
            return
        updated_rows = read_table()
        if idx >= len(updated_rows):
            return
        target = updated_rows[idx]
        try:
            c.setXYPosition(target.x, target.y)
            if target.z is not None:
                try:
                    c.setPosition(target.z)
                except Exception:
                    pass
        except Exception as exc:
            QMessageBox.warning(None, "Positions", f"Cannot move stage:\n{exc}")

    def on_update_from_stage() -> None:
        idx = getattr(table, "current_index", None)
        if idx is None or idx < 0 or idx >= len(rows):
            return
        try:
            x_pos, y_pos = c.getXYPosition()
            try:
                focus_device = c.getFocusDevice()
                z_val = float(c.getPosition()) if focus_device else None
            except Exception:
                z_val = None

            rows[idx].x = float(x_pos)
            rows[idx].y = float(y_pos)
            rows[idx].z = z_val
            write_table()
        except Exception as exc:
            QMessageBox.warning(None, "Positions", f"Cannot read stage:\n{exc}")

    def build_updated_sequence() -> Optional[MDASequence]:
        nonlocal seq
        if seq is None:
            QMessageBox.information(None, "Positions", "Load a sequence first.")
            return None
        updated_rows = read_table()
        stage_positions = tuple(row.to_useq() for row in updated_rows)
        return seq.model_copy(update={"stage_positions": stage_positions})

    def on_save() -> None:
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
        except Exception as exc:
            QMessageBox.critical(None, "Positions", f"Failed to save sequence:\n{exc}")

    def on_save_as() -> None:
        nonlocal seq_path, seq
        new_seq = build_updated_sequence()
        if new_seq is None:
            return
        dialog = QFileDialog()
        dialog.setAcceptMode(QFileDialog.AcceptSave)
        dialog.setNameFilters(
            [
                "useq JSON (*.useq.json)",
                "useq YAML (*.useq.yaml)",
                "JSON (*.json)",
                "YAML (*.yaml)",
            ]
        )
        if dialog.exec_():
            out_path = Path(dialog.selectedFiles()[0]).expanduser()
            try:
                _write_sequence(out_path, new_seq)
                set_status(f"Saved: {out_path.name}")
                seq_path = out_path
                seq = new_seq
            except Exception as exc:
                QMessageBox.critical(None, "Positions", f"Failed to save sequence:\n{exc}")

    load_btn.changed.connect(on_load)
    add_current_btn.changed.connect(on_add_current)
    add_points_btn.changed.connect(on_add_from_points)
    goto_btn.changed.connect(on_goto)
    update_from_stage_btn.changed.connect(on_update_from_stage)
    save_btn.changed.connect(on_save)
    save_as_btn.changed.connect(on_save_as)

    ui = Container(
        widgets=[
            Container(widgets=[file_edit, load_btn], layout="horizontal"),
            status,
            table,
            Container(widgets=[name_edit, add_current_btn], layout="horizontal"),
            Container(widgets=[Label(value="Points layer:"), points_layer, add_points_btn], layout="horizontal"),
            Container(widgets=[goto_btn, update_from_stage_btn], layout="horizontal"),
            Container(widgets=[save_btn, save_as_btn], layout="horizontal"),
        ],
        layout="vertical",
    )

    return ui
