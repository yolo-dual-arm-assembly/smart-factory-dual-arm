# Repository Guidelines

## Agent Scope & Environment Safety

Before editing files, identify exactly one owning package under `ros2_ws/src/`
for the task. By default, modify only that package and tests directly associated
with it. Prefer a package-local implementation even when a shared abstraction
would be more convenient.

Treat these paths as protected and do not modify them without explicit user
approval for the specific shared change:

- `ros2_ws/src/common/`
- `ros2_ws/src/project_interfaces/`
- every ROS2 package other than the owning package
- `main.py`, `pyproject.toml`, and `requirements.txt`
- repository-wide build, test, tooling, and environment configuration

If a package-local implementation is insufficient, stop before editing a
protected path and report:

1. the owning package and current allowed scope;
2. the exact protected files that would need to change;
3. why the change cannot remain package-local;
4. the expected impact on other packages and a local alternative, if one exists.

Agents must not use `sudo`, install packages globally, modify shell startup
files, alter global Git/Python/pip/ROS/OS configuration, create machine-wide
environment variables, or write outside this repository. Use only the
repository virtual environment and package-local configuration. Installing or
updating dependencies requires explicit user approval.

Do not import one ROS2 node package from another. Cross-node communication must
use ROS2 interfaces, and cross-package values must follow the dataclasses in the
`common` package. Do not move package-specific helpers into `common` merely for
convenience.

`system_monitor` is the one exception: the operator GUI is an application layer,
not a node, and must run without ROS2, so it may import `vision_inspection` and
`omx1_loading`. The dependency only ever points GUI → node package. A node
package must never import `system_monitor` — that breaks the colcon install,
which does not ship the GUI package.

Before finishing, run `git diff --name-only`, verify that every changed file is
inside the approved scope, and explicitly report any approved scope exception.

## Project Structure & Module Organization

A dual-OMX + YOLO inspection cell, split into five ROS2 nodes. One repository, one package per node, one owner per package.

- `main.py`: entry point for the integrated Tkinter GUI (runtime check, workspace path setup, then `system_monitor.ui.viewer:main`).
- `ros2_ws/src/common/`: shared by every package (ament_python, not a node) — `constants.py` (paths, `RobotState`, `RobotId`), `messages.py` (dataclass interchange formats), `logger.py`, `camera.py`, `serial_ports.py`, `omx_controller.py`, `bootstrap.py`. Laid out as `common/common/*.py`, so the import root is `ros2_ws/src/common` and imports stay `from common.x import y`.
- `ros2_ws/src/project_interfaces/`: `msg/DetectionResult.msg`, `srv/InspectBasket.srv`, `action/LoadBalls.action`, `action/SortBasket.action`. The definitions exist; no node serves the srv/action yet.
- `ros2_ws/src/vision_inspection/`: `vision_node.py` (rclpy), `inspection_logic.py` (basket verdict), `analysis.py`, `models.py`, `training.py`, `train.py` / `detect.py` (CLIs), `config/data.yaml`.
- `ros2_ws/src/omx1_loading/`: `loading_node.py` (rclpy), `coordinate_transform.py`, `camera_calibration.py`, vision/imitation runners, teaching data and window, `config/` for machine-specific calibration and taught poses (Git-ignored).
- `ros2_ws/src/omx2_sorting/`: basket move, pass/reject motions (scaffolded, no node yet).
- `ros2_ws/src/system_coordinator/`: `main_controller.py`, `state_machine.py`, `communication.py` (no node yet).
- `ros2_ws/src/system_monitor/`: `ui/` — viewer, webcam window, camera selector, OMX panel, manual control (no node yet).
- `models/`, `train_set/`, `object/`, `result/`: weights, dataset, inputs, outputs (all Git-ignored).
- `docs/`: `system_architecture.md`, `communication_protocol.md`, `calibration.md`. `ros2_ws/README.md` covers colcon build and node launch.
- `tests/`: pytest suite for non-UI logic.

ROS2 packages use the `pkg/pkg/*.py` layout, so the import root is the outer package folder. `common.bootstrap.ensure_workspace_path()` registers those paths at runtime and `pyproject.toml`'s `pythonpath` does it for pytest; `pip install -e .` makes `python -m <package>.<module>` work anywhere. `main.py` puts `ros2_ws/src/common` on `sys.path` itself, because the function that registers the rest lives inside `common`.

`PROJECT_DIR` (repo root, used for `object/`, `result/`, `models/`) is resolved by walking up for a directory holding both `main.py` and `ros2_ws`, not by a fixed number of `parents[]` steps — colcon copies `common` into `install/`, which changes the depth. Override it with `SMART_FACTORY_PROJECT_DIR` when running from outside the source tree.

Keep new logic in the matching package. Nodes never import each other — cross-node data goes through ROS2 interfaces, and any value crossing a package boundary must be a `common.messages` dataclass. Update `docs/communication_protocol.md` in the same PR when that format changes.

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
