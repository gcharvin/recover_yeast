from __future__ import annotations

import contextlib
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
    mda_button = PushButton(label="Use current MDA panel")
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

    def summarize_sequence(sequence: MDASequence) -> str:
        channel_names = ", ".join(ch.config for ch in sequence.channels) if sequence.channels else "default channel"
        positions = len(sequence.stage_positions)
        tp = sequence.time_plan
        if isinstance(tp, TIntervalLoops):
            interval = tp.interval.total_seconds()
            summary = f"{tp.loops} loops every {interval:.2f}s"
        elif tp is None:
            summary = "no time plan"
        else:
            summary = tp.__class__.__name__
        return f"Active MDA -> positions: {positions}, channels: {channel_names}, time plan: {summary}"

    def on_use_current_mda() -> None:
        nonlocal seq, seq_path
        try:
            import napari
            from napari_micromanager._gui_objects._mda_widget import MultiDWidget
        except ImportError:
            QMessageBox.information(
                None,
                "Time-lapse",
                "napari-micromanager is not available. Load a sequence file instead.",
            )
            return

        try:
            viewer = napari.current_viewer()
        except Exception:
            viewer = None

        if viewer is None:
            QMessageBox.information(
                None,
                "Time-lapse",
                "No napari viewer detected. Open napari-micromanager first.",
            )
            return

        dock_widgets = getattr(viewer.window, "_wrapped_dock_widgets", {})
        mda_widget: Optional[MultiDWidget] = None
        for dock in dock_widgets.values():
            inner = None
            with contextlib.suppress(AttributeError):
                inner = dock.inner_widget()
            if isinstance(inner, MultiDWidget):
                mda_widget = inner
                break

        if mda_widget is None:
            QMessageBox.information(
                None,
                "Time-lapse",
                "Cannot find the napari-micromanager MDA panel. Open it and try again.",
            )
            return

        try:
            seq = mda_widget.value().model_copy(deep=True)
        except Exception as exc:
            QMessageBox.critical(
                None,
                "Time-lapse",
                f"Failed to read the MDA panel:\n{exc}",
            )
            return

        seq_path = None
        status.value = summarize_sequence(seq)

    load_button.changed.connect(on_load)
    mda_button.changed.connect(on_use_current_mda)
    build_button.changed.connect(on_build)
    start_button.changed.connect(on_start)
    stop_button.changed.connect(on_stop)

    ui = Container(
        widgets=[
            status,
            Container(widgets=[file_edit, load_button, mda_button], layout="horizontal"),
            Container(widgets=[channel_combo, build_button], layout="horizontal"),
            Container(widgets=[start_button, stop_button], layout="horizontal"),
        ],
        layout="vertical",
    )

    return ui
