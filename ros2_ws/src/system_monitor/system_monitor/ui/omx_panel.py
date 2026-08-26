"""운영 대시보드에 삽입하는 OMX 1(적재) 도구 패널.

수동 관절 제어 창을 subprocess로 띄우고 그 생명주기를 관리한다. 도구는 시리얼
포트를 **직접** 열므로, 띄우기 전에 ``on_tool_start``로 대시보드가 포트를
내주고 끝나면 ``on_tool_end``로 되찾게 한다.

Mouse 교시·검출(캘리브레이션·교시 창·교시값 이동) UI는 실제 공정에서 쓰지 않아
패널에서 뺐다. 로직 자체는 ``omx1_loading``에 그대로 있으므로 필요해지면 이
패널에 버튼만 다시 붙이면 된다.

포트는 사용자가 입력하지 않고 ``omx_port`` 콜백이 준 자동 배정 값을 쓴다.
"""
from __future__ import annotations

import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable

from common.constants import PROJECT_DIR
from system_monitor.ui.device_roles import fallback_omx_port

PortCallback = Callable[[], "str | None"]
ToolLifecycleCallback = Callable[[str], None]


class OmxPanel(ttk.LabelFrame):
    """OMX 1 도구 버튼과 subprocess 생명주기를 한곳에서 관리한다."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        project_dir: Path = PROJECT_DIR,
        omx_port: PortCallback | None = None,
        on_tool_start: ToolLifecycleCallback | None = None,
        on_tool_end: ToolLifecycleCallback | None = None,
        on_calibrate: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(master, text="OMX 1 제어", padding=8)
        self.root = master.winfo_toplevel()
        self.project_dir = project_dir
        # 포트는 대시보드가 역할별로 배정한 값을 그대로 쓴다.
        self._omx_port = omx_port or (lambda: None)
        self._on_tool_start = on_tool_start or (lambda _tool: None)
        self._on_tool_end = on_tool_end or (lambda _tool: None)
        # 카메라 캘리브레이션 창은 카메라 소유·인계를 대시보드가 알아야 열 수
        # 있어(모방학습 캠을 계속 붙잡고 있는 CameraFeed와 겹치면 충돌한다),
        # 실제 로직은 대시보드에 맡기고 이 패널은 버튼만 갖는다.
        self._on_calibrate = on_calibrate or (lambda: None)

        self._tool_process: subprocess.Popen | None = None

        self._build_ui()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)

        ttk.Label(self, text="포트").grid(row=0, column=0, sticky="w")
        self.port_var = tk.StringVar(value=self.current_port_text())
        ttk.Label(
            self, textvariable=self.port_var, anchor="w", font="TkFixedFont"
        ).grid(row=1, column=0, sticky="ew", pady=(0, 6))

        self.manual_button = ttk.Button(
            self, text="수동 관절 제어", command=self.open_manual_control
        )
        self.manual_button.grid(row=2, column=0, sticky="ew", pady=2)

        self.calibrate_button = ttk.Button(
            self, text="카메라 캘리브레이션", command=self._on_calibrate
        )
        self.calibrate_button.grid(row=3, column=0, sticky="ew", pady=2)

        self.status_var = tk.StringVar(value="대기")
        ttk.Label(
            self, textvariable=self.status_var, wraplength=210, anchor="w"
        ).grid(row=4, column=0, sticky="ew", pady=(6, 0))

    def current_port_text(self) -> str:
        port = self._omx_port()
        return port if port else f"{fallback_omx_port()} (미검출)"

    def refresh_port(self) -> None:
        self.port_var.set(self.current_port_text())

    # ------------------------------------------------------------------ 가용성

    def is_busy(self) -> bool:
        """OMX 1 도구가 포트를 점유 중인지 반환한다."""
        return self._tool_process is not None and self._tool_process.poll() is None

    def set_external_busy(self, busy: bool) -> None:
        """통합 공정이 OMX1을 소유하는 동안 수동 제어·캘리브레이션 버튼을 잠근다."""
        if self.is_busy():
            return
        state = "disabled" if busy else "normal"
        self.manual_button.configure(state=state)
        self.calibrate_button.configure(state=state)

    def set_calibration_active(self, active: bool) -> None:
        """캘리브레이션 창이 카메라를 쥐고 있는 동안 다른 버튼을 잠근다.

        캘리브레이션은 subprocess가 아니라 대시보드 안에서 여는 Toplevel이라
        ``is_busy()``(포트 점유)로는 안 잡힌다 — 대시보드가 창을 열고 닫을
        때 직접 불러야 한다.
        """
        state = "disabled" if active else "normal"
        self.manual_button.configure(state=state)
        self.calibrate_button.configure(state=state)

    def _ensure_available(self) -> bool:
        if self.is_busy():
            messagebox.showwarning(
                "OMX 사용 중",
                "실행 중인 OMX 작업을 먼저 종료하세요.",
                parent=self.root,
            )
            return False
        if not self._omx_port():
            messagebox.showerror(
                "포트 없음",
                "OMX 시리얼 포트를 찾지 못했습니다.\n"
                "USB 연결과 전원을 확인한 뒤 다시 시도하세요.",
                parent=self.root,
            )
            return False
        return True

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
        self.manual_button.configure(state="disabled")
        self.calibrate_button.configure(state="disabled")
        self.after(250, self._poll_tool)

    def _poll_tool(self) -> None:
        process = self._tool_process
        if process is not None and process.poll() is None:
            self.after(250, self._poll_tool)
            return
        self._tool_process = None
        self._on_tool_end("manual_control")
        self.manual_button.configure(state="normal")
        self.calibrate_button.configure(state="normal")
        self.status_var.set("대기")

    # ------------------------------------------------------------------ 종료

    def request_close(self) -> bool:
        """종료를 준비하고 즉시 닫아도 되면 True를 반환한다."""
        if self.is_busy():
            messagebox.showinfo(
                "OMX 도구 실행 중",
                "수동 제어 창을 먼저 닫아 주세요.",
                parent=self.root,
            )
            return False
        return True
