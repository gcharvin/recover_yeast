#!/usr/bin/env python
"""External launcher for napari-micromanager time-lapse acquisitions.

The script loads an acquisition file exported from napari-micromanager
(`.useq.json` or `.json`), opens a small Tk interface, and lets the user
start the time-lapse through the Micro-Manager engine.

Dependencies:
    - pymmcore-plus
    - useq-schema
    - tkinter (standard library)
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import math
from pathlib import Path
from typing import Iterable, Optional

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from pymmcore_plus import CMMCorePlus
from useq import MDAEvent, MDASequence

try:
    # napari-micromanager stores the acquisition name in this metadata key
    from napari_micromanager._util import PYMMCW_METADATA_KEY
except ImportError:  # pragma: no cover
    PYMMCW_METADATA_KEY = "pymmcore_widgets"


LOG = logging.getLogger("timelapse_launcher")


def _read_sequence_file(path: Path) -> MDASequence:
    """Read a sequence exported by napari-micromanager."""
    try:
        return MDASequence.from_file(path)
    except ModuleNotFoundError as exc:
        if exc.name == "yaml":
            raise RuntimeError(
                "PyYAML is required to load YAML exports (*.useq.yaml). "
                "Install it with `pip install pyyaml`."
            ) from exc
        raise


def _sequence_name(sequence: MDASequence) -> str:
    meta = sequence.metadata.get(PYMMCW_METADATA_KEY, {})
    return str(meta.get("save_name", "Acquisition"))


def _total_events(sequence: MDASequence) -> int:
    shape = sequence.shape
    if shape:
        return math.prod(shape)
    return sum(1 for _ in sequence.iter_events())


def _sizes_summary(sequence: MDASequence) -> str:
    sizes = sequence.sizes
    labels = {
        "t": "time points",
        "p": "positions",
        "g": "grid points",
        "c": "channels",
        "z": "z planes",
    }
    parts: list[str] = []
    for axis in ("t", "p", "g", "c", "z"):
        value = sizes.get(axis)
        if value:
            parts.append(f"{value} {labels.get(axis, axis)}")
    return ", ".join(parts) if parts else "single image"


class TimelapseController:
    """Drive the Tk UI and interact with Micro-Manager."""

    def __init__(
        self,
        *,
        root: tk.Tk,
        core: CMMCorePlus,
        sequence: MDASequence,
        sequence_path: Path,
    ) -> None:
        self.root = root
        self.core = core
        self.sequence = sequence
        self.sequence_path = sequence_path
        self._frames_total = _total_events(sequence)
        self._frames_done = 0

        self.root.title("Micro-Manager time-lapse launcher")
        self.root.geometry("440x220")
        self.root.resizable(False, False)

        self.status_var = tk.StringVar(
            value=f"Ready to launch {sequence_path.name!r}."
        )
        self.summary_var = tk.StringVar(value=self._build_summary_text(sequence))
        self.sequence_var = tk.StringVar(value=str(sequence_path))

        self._build_ui()
        self._connect_signals()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # -- UI -----------------------------------------------------------------------
    def _build_ui(self) -> None:
        frame = ttk.Frame(self.root, padding=(12, 8))
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, textvariable=self.sequence_var, wraplength=400).pack(
            anchor=tk.W, pady=(0, 6)
        )
        ttk.Label(frame, textvariable=self.summary_var, wraplength=400).pack(
            anchor=tk.W
        )

        self.start_button = ttk.Button(
            frame,
            text="Start time-lapse",
            command=self.start_timelapse,
        )
        self.start_button.pack(fill=tk.X, pady=(16, 4))

        ttk.Button(frame, text="Select another file...", command=self.change_sequence).pack(
            fill=tk.X
        )

        ttk.Separator(frame).pack(fill=tk.X, pady=(12, 6))

        ttk.Label(frame, textvariable=self.status_var, wraplength=400).pack(
            anchor=tk.W
        )

    def _build_summary_text(self, sequence: MDASequence) -> str:
        name = _sequence_name(sequence)
        summary = _sizes_summary(sequence)
        total = self._frames_total if self._frames_total else "?"
        return f"Sequence {name!r} ({summary}) — {total} expected images."

    def _set_status(self, message: str) -> None:
        LOG.info(message)
        self.root.after(0, self.status_var.set, message)

    def _set_button_state(self, *, running: bool) -> None:
        state = tk.DISABLED if running else tk.NORMAL
        self.root.after(0, self.start_button.config, {"state": state})

    # -- Signal wiring -------------------------------------------------------------
    def _connect_signals(self) -> None:
        events = self.core.mda.events
        events.sequenceStarted.connect(self._sequence_started)  # type: ignore[arg-type]
        events.sequenceFinished.connect(self._sequence_finished)  # type: ignore[arg-type]
        events.sequenceCanceled.connect(self._sequence_canceled)  # type: ignore[arg-type]
        events.frameReady.connect(self._frame_ready)  # type: ignore[arg-type]

    def _disconnect_signals(self) -> None:
        events = self.core.mda.events
        with contextlib.suppress(Exception):
            events.sequenceStarted.disconnect(self._sequence_started)  # type: ignore[arg-type]
            events.sequenceFinished.disconnect(self._sequence_finished)  # type: ignore[arg-type]
            events.sequenceCanceled.disconnect(self._sequence_canceled)  # type: ignore[arg-type]
            events.frameReady.disconnect(self._frame_ready)  # type: ignore[arg-type]

    # -- Event callbacks -----------------------------------------------------------
    def _sequence_started(self, sequence: MDASequence, meta: dict | None = None) -> None:
        self._frames_done = 0
        self._set_button_state(running=True)
        self._set_status("Time-lapse started.")

    def _sequence_finished(self, sequence: MDASequence) -> None:
        self._set_button_state(running=False)
        self._set_status("Time-lapse completed.")

    def _sequence_canceled(self, sequence: MDASequence) -> None:
        self._set_button_state(running=False)
        self._set_status("Time-lapse canceled.")

    def _frame_ready(self, image, event: MDAEvent, metadata: dict) -> None:  # noqa: ANN001
        self._frames_done += 1
        total = self._frames_total or "?"
        self._set_status(f"Frame {self._frames_done}/{total} acquired.")

    # -- Actions -------------------------------------------------------------------
    def start_timelapse(self) -> None:
        if not self._micro_manager_ready():
            return
        if self.core.mda.is_running():
            messagebox.showwarning(
                "Already running",
                "A time-lapse is already running.",
                parent=self.root,
            )
            return
        self._set_status("Starting time-lapse...")
        try:
            self.core.run_mda(self.sequence)
        except RuntimeError as exc:
            if 'No device with label ""' in str(exc):
                self._handle_configuration_error(
                    "No focus device configured in Micro-Manager.\n\n"
                    "Load your Micro-Manager configuration (or pass --mm-config)\n"
                    "and ensure a focus drive is selected before starting the time-lapse."
                )
                return
            self._handle_run_error(exc)
        except Exception as exc:  # noqa: BLE001
            self._handle_run_error(exc)

    def _micro_manager_ready(self) -> bool:
        try:
            devices = tuple(self.core.getLoadedDevices())
        except Exception:  # pragma: no cover
            devices = ()

        missing: list[str] = []
        if len(devices) <= 1:
            missing.append(
                "No Micro-Manager configuration is currently loaded "
                "(only the Core device is available)."
            )

        focus_device = ""
        try:
            focus_device = self.core.getFocusDevice()
        except Exception:  # pragma: no cover
            focus_device = ""
        if not focus_device:
            missing.append("No focus drive is selected in Micro-Manager.")

        if missing:
            self._handle_configuration_error("\n".join(missing))
            return False

        return True

    def _handle_configuration_error(self, message: str) -> None:
        messagebox.showerror(
            "Micro-Manager not configured",
            f"Cannot start the time-lapse:\n\n{message}\n\n"
            "Open your Micro-Manager configuration (or provide --mm-config)\n"
            "then try again.",
            parent=self.root,
        )
        self._set_status("Micro-Manager configuration missing.")

    def _handle_run_error(self, exc: Exception) -> None:
        LOG.exception("Cannot start time-lapse")
        self._set_status("Failed to start the time-lapse.")
        messagebox.showerror(
            "Error",
            f"Cannot start the time-lapse:\n{exc}",
            parent=self.root,
        )
        self._set_button_state(running=False)

    def change_sequence(self) -> None:
        new_path = filedialog.askopenfilename(
            title="Select sequence file",
            filetypes=[
                ("useq JSON files", "*.useq.json"),
                ("useq YAML files", "*.useq.yaml;*.useq.yml"),
                ("JSON files", "*.json"),
                ("YAML files", "*.yaml;*.yml"),
                ("All files", "*.*"),
            ],
        )
        if not new_path:
            return
        try:
            sequence = _read_sequence_file(Path(new_path))
        except Exception as exc:  # noqa: BLE001
            LOG.exception("Failed to read sequence file")
            messagebox.showerror(
                "Read error",
                f"Cannot load {new_path}:\n{exc}",
                parent=self.root,
            )
            return
        self.sequence = sequence
        self.sequence_path = Path(new_path)
        self._frames_total = _total_events(sequence)
        self.summary_var.set(self._build_summary_text(sequence))
        self.sequence_var.set(str(self.sequence_path))
        self._set_status("Sequence ready.")

    # -- Cleanup -------------------------------------------------------------------
    def _on_close(self) -> None:
        if self.core.mda.is_running() and not messagebox.askyesno(
            "Time-lapse running",
            "A time-lapse is still running. Close anyway?",
            parent=self.root,
        ):
            return
        self._disconnect_signals()
        self.root.destroy()


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Trigger a Micro-Manager time-lapse from an exported file."
    )
    parser.add_argument(
        "--sequence",
        "-s",
        type=Path,
        help="Path to the .useq.json file exported by napari-micromanager.",
    )
    parser.add_argument(
        "--mm-config",
        type=Path,
        help="Path to the Micro-Manager configuration file (.cfg or .cfg.json).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO).",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Iterable[str]] = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level))

    mm_config = args.mm_config.expanduser().resolve() if args.mm_config else None

    root = tk.Tk()
    root.withdraw()  # hide while we possibly open dialogs

    if args.sequence:
        sequence_path = args.sequence.expanduser().resolve()
    else:
        sequence_file = filedialog.askopenfilename(
            title="Select exported file (.useq.json / .useq.yaml)",
            filetypes=[
                ("useq JSON files", "*.useq.json"),
                ("useq YAML files", "*.useq.yaml;*.useq.yml"),
                ("JSON files", "*.json"),
                ("YAML files", "*.yaml;*.yml"),
            ],
        )
        if not sequence_file:
            messagebox.showinfo("Cancelled", "No file selected. Exiting.")
            return
        sequence_path = Path(sequence_file)

    sequence = _read_sequence_file(sequence_path)

    core = CMMCorePlus.instance()
    if mm_config:
        LOG.info("Loading Micro-Manager configuration from %s", mm_config)
        core.loadSystemConfiguration(str(mm_config))

    root.deiconify()
    TimelapseController(
        root=root,
        core=core,
        sequence=sequence,
        sequence_path=sequence_path,
    )
    root.mainloop()


if __name__ == "__main__":
    main()
