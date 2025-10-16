# napari-mmc-tools

Small collection of utility widgets that integrate with napari-micromanager:

- **Shared TL Launcher** – start or stop a time-lapse from a saved `useq` sequence or from a single channel preset.
- **MDA Positions Editor** – inspect, edit, and save the `stage_positions` of a `useq` multi-dimensional acquisition file.

Both widgets rely on the `CMMCorePlus` singleton exposed by `pymmcore-plus`, so they are meant to run inside the same Python process as napari.

