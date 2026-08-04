# Repository Guidelines

## Project Structure & Module Organization

A dual-OMX + YOLO inspection cell, split into five ROS2 nodes. One repository, one package per node, one owner per package.

- `main.py`: entry point for the integrated Tkinter GUI (runtime check, workspace path setup, then `system_monitor.ui.viewer:main`).
- `common/`: shared by every package — `constants.py` (paths, `RobotState`, `RobotId`), `messages.py` (dataclass interchange formats), `logger.py`, `camera.py`, `serial_ports.py`, `omx_controller.py`, `bootstrap.py`.
- `ros2_ws/src/project_interfaces/`: `msg/DetectionResult.msg`. The `srv`/`action` definitions in `docs/communication_protocol.md` are not written yet.
- `ros2_ws/src/vision_inspection/`: `vision_node.py` (rclpy), `inspection_logic.py` (basket verdict), `analysis.py`, `models.py`, `training.py`, `train.py` / `detect.py` (CLIs), `config/data.yaml`.
- `ros2_ws/src/omx1_loading/`: `loading_node.py` (rclpy), `coordinate_transform.py`, `camera_calibration.py`, vision/imitation runners, teaching data and window, `config/` for machine-specific calibration and taught poses (Git-ignored).
- `ros2_ws/src/omx2_sorting/`: basket move, pass/reject motions (scaffolded, no node yet).
- `ros2_ws/src/system_coordinator/`: `main_controller.py`, `state_machine.py`, `communication.py` (no node yet).
- `ros2_ws/src/system_monitor/`: `ui/` — viewer, webcam window, camera selector, OMX panel, manual control (no node yet).
- `models/`, `train_set/`, `object/`, `result/`: weights, dataset, inputs, outputs (all Git-ignored).
- `docs/`: `system_architecture.md`, `communication_protocol.md`, `calibration.md`. `ros2_ws/README.md` covers colcon build and node launch.
- `tests/`: pytest suite for non-UI logic.

ROS2 packages use the `pkg/pkg/*.py` layout, so the import root is the outer package folder. `common.bootstrap.ensure_workspace_path()` registers those paths at runtime and `pyproject.toml`'s `pythonpath` does it for pytest; `pip install -e .` makes `python -m <package>.<module>` work anywhere.

Keep new logic in the matching package. Nodes never import each other — cross-node data goes through ROS2 interfaces, and any value crossing a package boundary must be a `common/messages.py` dataclass. Update `docs/communication_protocol.md` in the same PR when that format changes.

## Build, Test, and Development Commands

Create and activate a virtual environment on Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Run the desktop application with:

```powershell
python .\main.py
```

Before submitting changes, compile-check Python and run the tests with:

```powershell
python -m compileall common main.py ros2_ws/src
python -m pytest -q
```

Run every command from the repository root. ROS2 builds happen on Linux only (`cd ros2_ws && colcon build`); Windows development runs the GUI, CLIs, and tests without ROS2.

## Coding Style & Naming Conventions

Follow PEP 8 with four-space indentation and type annotations for public methods and non-obvious values. Use `snake_case` for functions and variables, `PascalCase` for classes, and `UPPER_SNAKE_CASE` for module constants. Keep Tkinter callbacks short; move inference and file operations into focused helper methods. Preserve the existing `pathlib.Path` approach instead of introducing raw path strings.

Use UTF-8 for Python, Markdown, CSV, and HTML files. Verify Korean UI text after editing to prevent encoding corruption.

## Testing Guidelines

Run the pytest suite in `tests/` with `python -m pytest -q` (install pytest via `python -m pip install pytest` or the `dev` extra). New non-UI logic should include `pytest` tests named `tests/test_<feature>.py`. For GUI or inference changes, manually verify model selection, single-image analysis, batch analysis, cached-result behavior, and clean application shutdown. Do not rely on generated files already present in `result/`.

## Commit & Pull Request Guidelines

Use concise imperative commits such as `Add telemetry playback controls` or `Fix cached preview refresh`, consistent with the existing history. Keep unrelated changes in separate commits.

Pull requests should describe behavior changes, manual test steps, and any model or data assumptions. Include screenshots for GUI or dashboard changes and link related issues. Avoid committing `.venv/`, caches, generated results, private images, or newly downloaded model weights; use Git LFS or release assets when weights must be distributed.
