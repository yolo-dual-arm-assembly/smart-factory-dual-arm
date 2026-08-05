"""운영 대시보드에 삽입하는 OMX 도구 패널과 작업 생명주기.

여기서 띄우는 도구(캘리브레이션·교시·Mouse 이동·수동 제어)는 모두 카메라나
시리얼 포트를 **직접** 연다. 대시보드가 같은 장치를 쥐고 있으면 열리지 않으므로,
도구를 띄우기 전에 ``on_tool_start``로 장치를 내주고 끝나면 ``on_tool_end``로
되찾게 한다. 어떤 도구가 무엇을 쓰는지는 대시보드의 ``TOOL_DEVICE_NEEDS``가 안다.

포트는 사용자가 입력하지 않고 ``omx_port`` 콜백이 준 자동 배정 값을 쓴다.
"""
from __future__ import annotations

import subprocess
import sys
import threading
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable

from common.constants import (
    OMX_CALIBRATION_PATH,
    OMX_MODEL_PATH,
    OMX_TEACHING_PATH,
    PROJECT_DIR,
)
from system_monitor.ui.device_roles import fallback_omx_port

# 카메라를 쓸 수 없으면 그 이유를, 쓸 수 있으면 None을 돌려준다.
CameraBusyCallback = Callable[[], "str | None"]
CameraIndexCallback = Callable[[], int]
PortCallback = Callable[[], "str | None"]
ToolLifecycleCallback = Callable[[str], None]
ShutdownReadyCallback = Callable[[], None]


def resource_status(calibration_path: Path, teaching_path: Path) -> str:
    """OMX 보정·교시 상태를 사용자용 문자열로 만든다."""
    calibration = (
        "좌표 보정 있음" if calibration_path.is_file() else "좌표 보정 없음"
    )
    if not teaching_path.is_file():
        return f"{calibration} · Mouse 관절 교시 필요"
    try:
        from omx1_loading.teaching import OmxTeachingDataset

        dataset = OmxTeachingDataset.load(teaching_path)
    except (ImportError, OSError, ValueError, TypeError, KeyError):
        return f"{calibration} · 교시 파일 오류"
    readiness = "자동 이동 가능" if dataset.is_ready else "추가 교시 필요"
    return f"{calibration} · 교시점 {dataset.point_count}개 · {readiness}"


class OmxPanel(ttk.LabelFrame):
    """OMX 관련 위젯, 보조 창, 워커 스레드를 한곳에서 관리한다."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        model_path: Path = OMX_MODEL_PATH,
        calibration_path: Path = OMX_CALIBRATION_PATH,
        teaching_path: Path = OMX_TEACHING_PATH,
        project_dir: Path = PROJECT_DIR,
        camera_busy_reason: CameraBusyCallback | None = None,
        camera_index: CameraIndexCallback | None = None,
        omx_port: PortCallback | None = None,
        on_tool_start: ToolLifecycleCallback | None = None,
        on_tool_end: ToolLifecycleCallback | None = None,
    ) -> None:
        super().__init__(master, text="OMX 비전 제어", padding=8)
        self.root = master.winfo_toplevel()
        self.model_path = model_path
        self.calibration_path = calibration_path
        self.teaching_path = teaching_path
        self.project_dir = project_dir
        self._camera_busy_reason = camera_busy_reason or (lambda: None)
        # 카메라와 포트는 대시보드가 역할별로 배정한 값을 그대로 쓴다.
        self._camera_index = camera_index or (lambda: 0)
        self._omx_port = omx_port or (lambda: None)
        self._on_tool_start = on_tool_start or (lambda _tool: None)
        self._on_tool_end = on_tool_end or (lambda _tool: None)

        self._runner = None
        self._vision_thread: threading.Thread | None = None
        self._tool_process: subprocess.Popen | None = None
        self._calibration_window = None
        self._teaching_window = None
        self._stop_requested = False
        self._shutdown_ready: ShutdownReadyCallback | None = None

        self._build_ui()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        self.columnconfigure((1, 3), weight=1)

        ttk.Label(self, text="포트").grid(row=0, column=0, sticky="w")
        self.port_var = tk.StringVar(value=self.current_port_text())
        ttk.Label(
            self, textvariable=self.port_var, anchor="w", font="TkFixedFont"
        ).grid(row=0, column=1, columnspan=3, sticky="ew", padx=(4, 0))

        self.calibrate_button = ttk.Button(
            self, text="1. 좌표 캘리브레이션", command=self.start_calibration
        )
        self.calibrate_button.grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0), padx=(0, 4)
        )
        self.manual_button = ttk.Button(
            self, text="수동 관절 제어", command=self.open_manual_control
        )
        self.manual_button.grid(
            row=1, column=2, columnspan=2, sticky="ew", pady=(8, 0), padx=(4, 0)
        )

        self.teaching_button = ttk.Button(
            self, text="2. Mouse 관절 교시 모드", command=self.open_teaching
        )
        self.teaching_button.grid(
            row=2, column=0, columnspan=4, sticky="ew", pady=(8, 0)
        )

        self.start_button = ttk.Button(
            self, text="3. 교시값으로 Mouse 이동", command=self.start_mouse_approach
        )
        self.start_button.grid(
            row=3, column=0, columnspan=3, sticky="ew", pady=(8, 0), padx=(0, 4)
        )
        self.stop_button = ttk.Button(
            self, text="종료/홈", command=self.stop_mouse_approach, state="disabled"
        )
        self.stop_button.grid(row=3, column=3, sticky="ew", pady=(8, 0), padx=(4, 0))

        self.status_var = tk.StringVar(value=self.current_resource_status())
        ttk.Label(
            self, textvariable=self.status_var, wraplength=320, anchor="w"
        ).grid(row=4, column=0, columnspan=4, sticky="ew", pady=(6, 0))

    def current_port_text(self) -> str:
        port = self._omx_port()
        return port if port else f"{fallback_omx_port()} (미검출)"

    def current_resource_status(self) -> str:
        return resource_status(self.calibration_path, self.teaching_path)

    def refresh_port(self) -> None:
        self.port_var.set(self.current_port_text())

    # ------------------------------------------------------------------ 가용성

    def is_busy(self) -> bool:
        """OMX 작업이 로봇이나 카메라를 점유 중인지 반환한다."""
        vision_running = (
            self._vision_thread is not None and self._vision_thread.is_alive()
        )
        tool_running = (
            self._tool_process is not None and self._tool_process.poll() is None
        )
        return (
            vision_running
            or tool_running
            or self._window_exists(self._calibration_window)
            or self._window_exists(self._teaching_window)
        )

    @staticmethod
    def _window_exists(window) -> bool:
        return window is not None and bool(window.winfo_exists())

    def _ensure_available(self, *, needs_port: bool = True) -> bool:
        if self.is_busy():
            messagebox.showwarning(
                "OMX 사용 중",
                "실행 중인 OMX 작업을 먼저 종료하세요.",
                parent=self.root,
            )
            return False
        camera_busy = self._camera_busy_reason()
        if camera_busy is not None:
            messagebox.showwarning("카메라 사용 중", camera_busy, parent=self.root)
            return False
        if needs_port and not self._omx_port():
            messagebox.showerror(
                "포트 없음",
                "OMX 시리얼 포트를 찾지 못했습니다.\n"
                "USB 연결과 전원을 확인한 뒤 다시 시도하세요.",
                parent=self.root,
            )
            return False
        return True

    # ------------------------------------------------------------------ 캘리브레이션

    def start_calibration(self) -> None:
        if not self._ensure_available(needs_port=False):
            return
        self._on_tool_start("calibration")
        try:
            from omx1_loading.camera_calibration import OmxCalibrationWindow

            self._calibration_window = OmxCalibrationWindow(
                self.root,
                camera_index=self._camera_index(),
                save_path=self.calibration_path,
                on_saved=self._calibration_saved,
                on_closed=self._calibration_closed,
            )
        except Exception as error:
            self._on_tool_end("calibration")
            messagebox.showerror("캘리브레이션 오류", str(error), parent=self.root)
            return
        self.status_var.set("좌표 캘리브레이션 창 실행 중")
        self._calibration_window.transient(self.root)

    def _calibration_saved(self) -> None:
        self.status_var.set(f"캘리브레이션 준비됨 · {self.calibration_path.name}")

    def _calibration_closed(self) -> None:
        self._calibration_window = None
        self._on_tool_end("calibration")
        self.status_var.set(self.current_resource_status())

    # ------------------------------------------------------------------ 교시

    def open_teaching(self) -> None:
        if not self._ensure_available():
            return
        self._on_tool_start("teaching")
        try:
            from omx1_loading.teaching_window import OmxTeachingWindow

            self._teaching_window = OmxTeachingWindow(
                self.root,
                model_path=self.model_path,
                teaching_path=self.teaching_path,
                port=self._omx_port() or fallback_omx_port(),
                camera_index=self._camera_index(),
                on_changed=self._teaching_changed,
                on_closed=self._teaching_closed,
            )
        except Exception as error:
            self._on_tool_end("teaching")
            messagebox.showerror("Mouse 교시 오류", str(error), parent=self.root)
            return
        self.status_var.set("Mouse 관절 교시 모드 실행 중")
        self._teaching_window.transient(self.root)

    def _teaching_changed(self) -> None:
        self.status_var.set(self.current_resource_status())

    def _teaching_closed(self) -> None:
        self._teaching_window = None
        self._on_tool_end("teaching")
        self.status_var.set(self.current_resource_status())

    # ------------------------------------------------------------------ 수동 제어

    def open_manual_control(self) -> None:
        if not self._ensure_available():
            return
        self._on_tool_start("manual_control")
        # 같은 폴더의 파일이므로 __file__ 기준으로 찾는다. 폴더가 옮겨져도
        # 경로 문자열을 다시 고칠 필요가 없다.
        manual_control = Path(__file__).with_name("omx_manual_control.py")
        command = [
            sys.executable,
            str(manual_control),
            "--port",
            self._omx_port() or fallback_omx_port(),
        ]
        try:
            self._tool_process = subprocess.Popen(command, cwd=self.project_dir)
        except Exception as error:
            self._on_tool_end("manual_control")
            messagebox.showerror("OMX 실행 오류", str(error), parent=self.root)
            return
        self.status_var.set("수동 관절 제어 창 실행 중")
        self._set_controls(running=True, allow_stop=False)
        self.after(250, self._poll_tool)

    def _poll_tool(self) -> None:
        process = self._tool_process
        if process is not None and process.poll() is None:
            self.after(250, self._poll_tool)
            return
        self._tool_process = None
        self._on_tool_end("manual_control")
        self._set_controls(running=False)
        self.status_var.set(self.current_resource_status())

    # ------------------------------------------------------------------ Mouse 이동

    def start_mouse_approach(self) -> None:
        if not self._ensure_available():
            return
        if not self.teaching_path.is_file():
            messagebox.showerror(
                "Mouse 관절 교시 필요",
                "Mouse 관절 교시 모드에서 최소 4개 자세를 먼저 저장하세요.",
                parent=self.root,
            )
            return
        if not self.model_path.is_file():
            messagebox.showerror(
                "모델 오류", f"모델 파일 없음:\n{self.model_path}", parent=self.root
            )
            return

        self._on_tool_start("mouse_approach")
        self._set_controls(running=True, allow_stop=True)
        self.status_var.set("Mouse 모델 준비 및 로봇 연결 중...")
        self._stop_requested = False
        self._vision_thread = threading.Thread(
            target=self._mouse_approach_worker,
            args=(self._omx_port() or fallback_omx_port(), self._camera_index()),
            daemon=True,
        )
        self._vision_thread.start()

    def _mouse_approach_worker(self, port: str, camera_index: int) -> None:
        error: str | None = None
        try:
            from common.omx_controller import OmxConfig
            from omx1_loading.imitation_control import OmxTaughtVisionRunner
            from omx1_loading.teaching import OmxTeachingDataset

            teaching = OmxTeachingDataset.load(self.teaching_path)
            runner = OmxTaughtVisionRunner(
                model_path=self.model_path,
                teaching=teaching,
                config=OmxConfig(port=port),
                confidence=0.5,
                hit_frames=5,
                camera_index=camera_index,
            )
            self._runner = runner
            if self._stop_requested:
                runner.request_stop()
            self.after(
                0,
                self.status_var.set,
                "교시 기반 Mouse 탐지 중 · Q: 종료, R: 홈",
            )
            runner.run()
        except Exception as exc:
            error = str(exc)
            traceback.print_exc()
        finally:
            self._runner = None
            self.after(0, self._mouse_approach_finished, error)

    def stop_mouse_approach(self) -> None:
        self._stop_requested = True
        if self._runner is not None:
            self.status_var.set("종료 요청됨 · 홈 복귀 중...")
            self._runner.request_stop()

    def _mouse_approach_finished(self, error: str | None) -> None:
        self._vision_thread = None
        self._on_tool_end("mouse_approach")
        self._set_controls(running=False)
        self.status_var.set(self.current_resource_status())
        if error is not None:
            messagebox.showerror("OMX 비전 오류", error, parent=self.root)

        shutdown_ready, self._shutdown_ready = self._shutdown_ready, None
        if shutdown_ready is not None:
            shutdown_ready()

    # ------------------------------------------------------------------ 상태/종료

    def _set_controls(self, running: bool, allow_stop: bool = False) -> None:
        normal_state = "disabled" if running else "normal"
        for widget in (
            self.calibrate_button,
            self.manual_button,
            self.teaching_button,
            self.start_button,
        ):
            widget.configure(state=normal_state)
        self.stop_button.configure(
            state="normal" if running and allow_stop else "disabled"
        )

    def request_close(self, on_ready: ShutdownReadyCallback) -> bool:
        """종료를 준비하고 즉시 닫아도 되면 True를 반환한다."""
        if self._vision_thread is not None and self._vision_thread.is_alive():
            self._shutdown_ready = on_ready
            self.status_var.set("종료 요청 중 · 홈 복귀를 기다리는 중...")
            self.stop_mouse_approach()
            return False
        if self._tool_process is not None and self._tool_process.poll() is None:
            messagebox.showinfo(
                "OMX 도구 실행 중",
                "수동 제어 창을 먼저 닫아 주세요.",
                parent=self.root,
            )
            return False

        for window in (self._calibration_window, self._teaching_window):
            if self._window_exists(window):
                window.close()
        return True
