"""공 Pick & Place 단독 GUI — ROS2 없이 카메라+YOLO+로봇팔을 직접 제어한다.

메인 대시보드(``ui/viewer.py``)와 별개로 띄우는 독립 창이다. 실시간
카메라 화면·탐지 좌표·상태는 ``pick_ball.OmxVisionRunner``가 여는
"OMX Vision Control" 창에 표시되고, 이 Tk 창은 시작/중단 버튼과 상태만
보여준다.

실행 (저장소 루트 어디서든, 별도 설치 없이)::

    python ros2_ws/src/system_monitor/system_monitor/ball_pick_gui.py
"""
from __future__ import annotations

import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

# 대시보드 없이 이 파일만 실행할 때(직접 실행이든 `python -m`이든)를 위한
# 부트스트랩. `-m`으로 실행해도 __package__만 채워질 뿐 형제 패키지
# (omx1_loading 등)는 sys.path에 안 잡히므로 항상 실행한다. common 자체는
# bootstrap 함수가 그 안에 있어서 먼저 경로에 넣어야 하고, 나머지
# (omx1_loading, system_monitor)는 ensure_workspace_path()가 등록한다.
_workspace_src = Path(__file__).resolve().parents[2]  # ros2_ws/src
sys.path.insert(0, str(_workspace_src / "common"))
from common.bootstrap import ensure_workspace_path  # noqa: E402

ensure_workspace_path(_workspace_src)

from common.constants import OMX_CALIBRATION_PATH, PROJECT_DIR
from common.omx_controller import OmxConfig
from common.serial_ports import list_serial_ports
from omx1_loading.camera_calibration import OmxCalibrationWindow
from omx1_loading.coordinate_transform import OmxCalibration
from omx1_loading.pick_ball import OmxVisionRunner, State
from system_monitor.ui.device_roles import assign_omx_ports, fallback_omx_port
from system_monitor.ui.ui_fonts import configure_korean_fonts

# common.constants.OMX_MODEL_PATH는 교시 데모용 범용 COCO 가중치라 공
# 인식에는 안 맞는다 — 저장소 루트의 커스텀 학습 가중치를 기본값으로 쓴다.
BALL_MODEL_PATH = PROJECT_DIR / "best.pt"


def default_port() -> str:
    """적재 팔(OMX 1) 포트를 자동 배정하고, 못 찾으면 안내용 기본값을 준다."""
    loading_port, _sorting_port = assign_omx_ports(list_serial_ports())
    return loading_port or fallback_omx_port()


class BallPickGuiApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        configure_korean_fonts(self)
        self.title("공 Pick & Place")
        self.geometry("440x260")
        self.resizable(False, False)

        self._runner: OmxVisionRunner | None = None
        self._thread: threading.Thread | None = None

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        frame = ttk.Frame(self, padding=12)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text=f"모델: {BALL_MODEL_PATH}").pack(anchor="w")
        ttk.Label(frame, text=f"캘리브레이션: {OMX_CALIBRATION_PATH}").pack(
            anchor="w", pady=(2, 0)
        )
        self.calibrate_button = ttk.Button(
            frame, text="캘리브레이션 열기", command=self.open_calibration
        )
        self.calibrate_button.pack(fill="x", pady=(8, 0))

        self.status_var = tk.StringVar(value="대기 중")
        ttk.Label(
            frame, textvariable=self.status_var, wraplength=400, foreground="#0a7"
        ).pack(anchor="w", pady=(10, 10))

        button_row = ttk.Frame(frame)
        button_row.pack(fill="x")
        self.start_button = ttk.Button(button_row, text="시작", command=self.start)
        self.start_button.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self.stop_button = ttk.Button(
            button_row, text="중단", command=self.stop, state="disabled"
        )
        self.stop_button.pack(side="left", expand=True, fill="x", padx=(4, 0))

        ttk.Label(
            frame,
            text=(
                "시작하면 별도 카메라 창(OMX Vision Control)이 뜹니다.\n"
                "그 창에서 Q=완전 종료, R=홈 복귀(탐지는 계속)."
            ),
            foreground="#666",
            wraplength=400,
            justify="left",
        ).pack(anchor="w", pady=(14, 0))

    # ------------------------------------------------------------------ 캘리브레이션

    def open_calibration(self) -> None:
        if self._runner is not None:
            messagebox.showwarning(
                "실행 중",
                "Pick & Place 실행 중에는 캘리브레이션을 열 수 없습니다.",
                parent=self,
            )
            return
        try:
            OmxCalibrationWindow(
                self, camera_index=0, save_path=OMX_CALIBRATION_PATH
            )
        except Exception as error:
            messagebox.showerror("카메라 오류", str(error), parent=self)

    # ------------------------------------------------------------------ 실행

    def start(self) -> None:
        if not OMX_CALIBRATION_PATH.is_file():
            messagebox.showerror(
                "캘리브레이션 없음",
                f"캘리브레이션 파일이 없습니다:\n{OMX_CALIBRATION_PATH}\n\n"
                "먼저 캘리브레이션을 진행하세요.",
                parent=self,
            )
            return
        if not BALL_MODEL_PATH.is_file():
            messagebox.showerror(
                "모델 없음", f"모델 파일이 없습니다:\n{BALL_MODEL_PATH}", parent=self
            )
            return

        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.calibrate_button.configure(state="disabled")
        self.status_var.set("모델 로딩 및 로봇 연결 중...")

        self._thread = threading.Thread(target=self._run_worker, daemon=True)
        self._thread.start()

    def _run_worker(self) -> None:
        error: str | None = None
        try:
            calibration = OmxCalibration.load(OMX_CALIBRATION_PATH)
            runner = OmxVisionRunner(
                model_path=BALL_MODEL_PATH,
                calibration=calibration,
                config=OmxConfig(port=default_port()),
                confidence=0.5,
                hit_frames=3,
                camera_index=0,
                max_stage=State.HOME,
            )
            self._runner = runner
            self.after(0, self.status_var.set, "탐지 중 · 카메라 창에서 Q=종료, R=홈")
            runner.run()
        except Exception as exc:  # noqa: BLE001 — GUI 스레드로 그대로 보고한다.
            error = str(exc)
        finally:
            self._runner = None
            self.after(0, self._finished, error)

    def _finished(self, error: str | None) -> None:
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.calibrate_button.configure(state="normal")
        self.status_var.set("대기 중")
        if error is not None:
            messagebox.showerror("실행 오류", error, parent=self)

    def stop(self) -> None:
        if self._runner is not None:
            self.status_var.set("종료 요청됨 · 홈 복귀 중...")
            self._runner.request_stop()

    # ------------------------------------------------------------------ 종료

    def _on_close(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            self.stop()
            self.after(200, self._wait_and_close)
        else:
            self.destroy()

    def _wait_and_close(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            self.after(200, self._wait_and_close)
        else:
            self.destroy()


def main() -> None:
    app = BallPickGuiApp()
    app.mainloop()


if __name__ == "__main__":
    main()
