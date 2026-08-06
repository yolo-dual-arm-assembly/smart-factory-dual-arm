"""OMX2(분류) 동작 패널 — 교시된 PASS/REJECT 웨이포인트를 실행한다.

동작 자체는 :mod:`omx2_sorting`의 ``pass_motion.run`` / ``reject_motion.run``을
그대로 부른다. 동작 순서는 그 패키지가 소유하고, 이 패널은 버튼·스레드·장치
인계만 담당한다.

포트는 대시보드가 배정한 **분류 팔(OMX 2)** 포트 콜백을 쓴다. omx2_sorting의
터미널 스크립트들은 기본 포트 자동 선택을 쓰는데, 그건 첫 번째 포트(보통
OMX 1)를 잡으므로 두 팔이 연결된 상태에서는 **적재 팔이 움직이는 사고**가
난다. GUI 경로는 반드시 배정된 포트를 명시적으로 넘긴다.

실행은 수동 버튼뿐이다. 검수 판정과 자동 연동하지 않는다 — 아직 사람이 눌러
확인하며 검증하는 단계다.
"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from common.constants import RobotState
from common.messages import InspectionResult, RobotStatus
from common.omx_controller import OmxConfig, OmxController

PortCallback = Callable[[], str | None]
ToolLifecycleCallback = Callable[[str], None]

# TOOL_DEVICE_NEEDS의 키. 모션 실행과 교시 모두 분류 팔 하나만 쓴다.
TOOL_MOTION = "sorting_motion"
TOOL_TEACHING = "sorting_teaching"

# run()들은 판정 방향만 확인하므로(is_pass) 수동 실행용 최소 결과를 만들어 넘긴다.
MANUAL_PASS = InspectionResult(total_count=1, defect_count=0, result=RobotState.PASS)
MANUAL_REJECT = InspectionResult(total_count=1, defect_count=1, result=RobotState.REJECT)


class SortingPanel(ttk.LabelFrame):
    """분류 팔의 교시·실행 버튼과 워커 스레드를 한곳에서 관리한다."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        omx_port: PortCallback | None = None,
        on_tool_start: ToolLifecycleCallback | None = None,
        on_tool_end: ToolLifecycleCallback | None = None,
    ) -> None:
        super().__init__(master, text="OMX 2 분류 제어", padding=8)
        self.root = master.winfo_toplevel()
        self._omx_port = omx_port or (lambda: None)
        self._on_tool_start = on_tool_start or (lambda _tool: None)
        self._on_tool_end = on_tool_end or (lambda _tool: None)

        self._motion_thread: threading.Thread | None = None
        self._teach_window = None

        self._build_ui()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)

        ttk.Label(self, text="포트").grid(row=0, column=0, sticky="w")
        self.port_var = tk.StringVar(value=self.current_port_text())
        ttk.Label(
            self, textvariable=self.port_var, anchor="w", font="TkFixedFont"
        ).grid(row=1, column=0, sticky="ew", pady=(0, 6))

        self.teach_button = ttk.Button(
            self, text="1. 분류 동작 교시", command=self.open_teaching
        )
        self.teach_button.grid(row=2, column=0, sticky="ew", pady=2)
        self.pass_button = ttk.Button(
            self, text="2. PASS 동작 실행", command=lambda: self.start_motion("PASS")
        )
        self.pass_button.grid(row=3, column=0, sticky="ew", pady=2)
        self.reject_button = ttk.Button(
            self, text="3. REJECT 동작 실행", command=lambda: self.start_motion("REJECT")
        )
        self.reject_button.grid(row=4, column=0, sticky="ew", pady=2)

        self.status_var = tk.StringVar(value="대기")
        ttk.Label(self, textvariable=self.status_var, anchor="w", wraplength=210).grid(
            row=5, column=0, sticky="ew", pady=(6, 0)
        )

    # ------------------------------------------------------------------ 상태

    def current_port_text(self) -> str:
        return self._omx_port() or "배정 안 됨"

    def refresh_port(self) -> None:
        self.port_var.set(self.current_port_text())

    def is_busy(self) -> bool:
        if self._motion_thread is not None and self._motion_thread.is_alive():
            return True
        return self._teach_window is not None and bool(
            self._teach_window.winfo_exists()
        )

    def _ensure_available(self) -> bool:
        if self.is_busy():
            messagebox.showwarning(
                "실행 중", "분류 동작이나 교시 창을 먼저 끝내 주세요.", parent=self.root
            )
            return False
        if not self._omx_port():
            messagebox.showwarning(
                "포트 없음",
                "OMX 2에 배정된 시리얼 포트가 없습니다.\n"
                "두 번째 로봇 보드가 연결됐는지 확인하세요.",
                parent=self.root,
            )
            return False
        return True

    # ------------------------------------------------------------------ 교시

    def open_teaching(self) -> None:
        if not self._ensure_available():
            return
        from system_monitor.ui.sorting_teach_window import SortingTeachWindow

        port = self._omx_port()
        assert port is not None
        self._on_tool_start(TOOL_TEACHING)
        try:
            self._teach_window = SortingTeachWindow(
                self.root, port, on_closed=self._teaching_closed
            )
        except Exception as error:
            self._on_tool_end(TOOL_TEACHING)
            messagebox.showerror("교시 창 오류", str(error), parent=self.root)

    def _teaching_closed(self) -> None:
        self._teach_window = None
        self._on_tool_end(TOOL_TEACHING)

    # ------------------------------------------------------------------ 실행

    def start_motion(self, motion: str) -> None:
        if not self._ensure_available():
            return
        if not messagebox.askyesno(
            f"{motion} 동작 실행",
            f"OMX 2가 교시된 {motion} 동작을 실제로 수행합니다.\n"
            "작업 영역이 비어 있는지 확인했습니까?",
            parent=self.root,
        ):
            return
        port = self._omx_port()
        assert port is not None
        self._on_tool_start(TOOL_MOTION)
        self._set_motion_buttons(enabled=False)
        self.status_var.set(f"{motion} 동작 실행 중...")
        self._motion_thread = threading.Thread(
            target=self._motion_worker, args=(motion, port), daemon=True
        )
        self._motion_thread.start()

    def _motion_worker(self, motion: str, port: str) -> None:
        # 동작 정의는 omx2_sorting이 소유한다. 여기서 waypoint를 다시 읽지 않는다.
        from omx2_sorting import pass_motion, reject_motion

        controller = OmxController(OmxConfig(port=port))
        try:
            controller.connect()
            if motion == "PASS":
                status = pass_motion.run(controller, MANUAL_PASS)
            else:
                status = reject_motion.run(controller, MANUAL_REJECT)
        except Exception as error:
            status = RobotStatus(
                "OMX_2", RobotState.ERROR, success=False, message=str(error)
            )
        finally:
            try:
                # disconnect는 토크를 끄므로 동작이 끝난(또는 실패한) 자세에서
                # 팔이 처질 수 있다. 교시 마지막 스텝을 안정 자세로 잡아 둘 것.
                controller.disconnect()
            except Exception:
                pass
        try:
            self.after(0, self._motion_done, motion, status)
        except (RuntimeError, tk.TclError):
            # 동작 중에 대시보드가 이미 닫혔다. 알릴 화면이 없다.
            pass

    def _motion_done(self, motion: str, status: RobotStatus) -> None:
        if not self.winfo_exists():
            return
        self._motion_thread = None
        self._set_motion_buttons(enabled=True)
        self._on_tool_end(TOOL_MOTION)
        if status.success:
            self.status_var.set(f"{motion} 완료 — {status.message}")
        else:
            self.status_var.set(f"{motion} 실패 — {status.message}")
        print(f"[분류] {motion}: {status.to_dict()}")

    def _set_motion_buttons(self, *, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for button in (self.teach_button, self.pass_button, self.reject_button):
            button.configure(state=state)

    # ------------------------------------------------------------------ 종료

    def request_close(self) -> bool:
        """대시보드 종료 직전에 부른다. 닫아도 되면 True."""
        if self._motion_thread is not None and self._motion_thread.is_alive():
            messagebox.showinfo(
                "분류 동작 실행 중",
                "동작이 끝날 때까지 기다린 뒤 닫아 주세요.",
                parent=self.root,
            )
            return False
        if self._teach_window is not None and self._teach_window.winfo_exists():
            # 교시 창의 토크 경고 흐름을 그대로 태운다.
            self._teach_window._on_close()
            if self._teach_window is not None:
                return False
        return True
