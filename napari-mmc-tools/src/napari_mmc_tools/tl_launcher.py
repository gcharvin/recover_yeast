from __future__ import annotations

from pathlib import Path
from typing import Optional

from magicgui.widgets import ComboBox, Container, FileEdit, Label, PushButton
from qtpy.QtWidgets import QMessageBox
from useq import Channel, MDASequence, TIntervalLoops

from ._shared import core


def _load_sequence(path: Path) -> MDASequence:
    return MDASequence.from_file(path)


def _build_simple_sequence(channel_name: str, exposure_ms: float) -> MDASequence:
    return MDASequence(
        time_plan=TIntervalLoops(interval=5.0, loops=60),
        channels=(Channel(config=channel_name, exposure=exposure_ms),),
    )


def widget() -> Container:
    c = core()

    status = Label(value="Load a sequence file or build a simple time-lapse.")
    file_edit = FileEdit(mode="r", label="Sequence (*.useq.json | *.useq.yaml | *.json | *.yaml)")
    load_button = PushButton(label="Load sequence")
    start_button = PushButton(label="Start time-lapse")
    stop_button = PushButton(label="Stop")

    try:
        channel_presets = list(c.getAvailableConfigs("Channel"))
    except Exception:
        channel_presets = []
    channel_presets = channel_presets or ["(none)"]
    channel_combo = ComboBox(label="Channel preset", choices=channel_presets)
    build_button = PushButton(label="Build simple TL (5s × 60)")

    seq: Optional[MDASequence] = None
    seq_path: Optional[Path] = None

    def on_load() -> None:
        nonlocal seq, seq_path
        value = file_edit.value
        if not value:
            QMessageBox.information(None, "Time-lapse", "Select a sequence file first.")
            return
        path = Path(value).expanduser()
        if not path.exists():
            QMessageBox.warning(None, "Time-lapse", f"File not found: {path}")
            return
        try:
            seq = _load_sequence(path)
            seq_path = path
            status.value = f"Loaded: {path.name}"
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(None, "Time-lapse", f"Cannot read sequence:\n{exc}")

    def on_build() -> None:
        nonlocal seq, seq_path
        channel_name = channel_combo.value
        if not channel_name or channel_name == "(none)":
            QMessageBox.information(None, "Time-lapse", "No channel preset selected.")
            return
        try:
            exposure_ms = float(c.getExposure())
        except Exception:
            exposure_ms = 20.0
        seq = _build_simple_sequence(channel_name, exposure_ms)
        seq_path = None
        status.value = f"Built time-lapse: channel={channel_name}, exposure={exposure_ms:.1f} ms"

    def on_start() -> None:
        if c.mda.is_running():
            QMessageBox.information(None, "Time-lapse", "An acquisition is already running.")
            return
        if seq is None:
            QMessageBox.information(None, "Time-lapse", "Load or build a sequence first.")
            return
        try:
            c.mda.run(seq)
            status.value = "Starting time-lapse..."
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(None, "Time-lapse", f"Failed to start acquisition:\n{exc}")

    def on_stop() -> None:
        try:
            if c.mda.is_running():
                c.mda.cancel()
                status.value = "Acquisition cancelled."
        except Exception as exc:
            QMessageBox.warning(None, "Time-lapse", f"Cannot cancel acquisition:\n{exc}")

    load_button.changed.connect(on_load)
    build_button.changed.connect(on_build)
    start_button.changed.connect(on_start)
    stop_button.changed.connect(on_stop)

    ui = Container(
        widgets=[
            status,
            Container(widgets=[file_edit, load_button], layout="horizontal"),
            Container(widgets=[channel_combo, build_button], layout="horizontal"),
            Container(widgets=[start_button, stop_button], layout="horizontal"),
        ],
        layout="vertical",
    )

    return ui
