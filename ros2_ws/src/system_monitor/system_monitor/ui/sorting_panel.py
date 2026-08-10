"""OMX2(분류) 동작 패널 — 교시된 PASS/REJECT 웨이포인트를 실행한다.

동작 자체는 :mod:`omx2_sorting`의 ``pass_motion.run`` / ``reject_motion.run``을
그대로 부른다. 동작 순서는 그 패키지가 소유하고, 이 패널은 버튼·스레드·장치
인계만 담당한다.

포트는 대시보드가 배정한 **분류 팔(OMX 2)** 포트 콜백을 쓴다. omx2_sorting의
터미널 스크립트들은 기본 포트 자동 선택을 쓰는데, 그건 첫 번째 포트(보통
OMX 1)를 잡으므로 두 팔이 연결된 상태에서는 **적재 팔이 움직이는 사고**가
난다. GUI 경로는 반드시 배정된 포트를 명시적으로 넘긴다.

패널 버튼은 사람이 눌러 검증하는 수동 실행이다. 통합 공정은 아래의
:func:`execute_sorting_motion`을 재사용해 확정된 검사 판정을 넘긴다.
"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from common.constants import RobotState
from common.messages import InspectionResult, RobotStatus
from common.omx_controller import OmxCommunicationError, OmxConfig, OmxController

PortCallback = Callable[[], str | None]
ToolLifecycleCallback = Callable[[str], None]

# TOOL_DEVICE_NEEDS의 키. 모션 실행과 교시 모두 분류 팔 하나만 쓴다.
TOOL_MOTION = "sorting_motion"
TOOL_TEACHING = "sorting_teaching"

# run()들은 판정 방향만 확인하므로(is_pass) 수동 실행용 최소 결과를 만들어 넘긴다.
MANUAL_PASS = InspectionResult(total_count=1, defect_count=0, result=RobotState.PASS)
MANUAL_REJECT = InspectionResult(total_count=1, defect_count=1, result=RobotState.REJECT)

# 종료할 때 중단을 요청하고 워커가 정리를 끝낼 때까지 기다리는 시간. 토크 해제와
# 포트 닫기만 남은 상태라 짧아도 충분하고, 넘겨도 daemon 스레드라 종료를 막지 않는다.
MOTION_STOP_TIMEOUT_SEC = 3.0


def check_sorting_motors(controller: OmxController) -> None:
    """웨이포인트 실행 전에 분류 팔이 실제로 응답하는지 확인한다."""
    missing = controller.find_missing_motors()
    if not missing:
        return
    if len(missing) == len(controller.expected_motor_ids()):
        raise OmxCommunicationError(
            f"{controller.config.port} 포트는 열렸지만 응답하는 모터가 "
            f"없습니다 (확인한 ID: {missing}).\n"
            "OMX 2의 전원, USB 케이블, 포트 배정을 확인하세요."
        )
    # 기존 수동 실행 정책을 유지한다. 일부 모터 누락은 콘솔에 경고하고
    # 웨이포인트 실행기가 각 명령의 성공/실패를 판단하게 한다.
    print(f"[분류] 경고: 응답 없는 모터 ID {missing}")


def execute_sorting_motion(
    controller: OmxController, inspection: InspectionResult
) -> RobotStatus:
    """이미 연결된 컨트롤러로 검사 판정에 맞는 분류 동작을 한 번 실행한다."""
    from omx2_sorting import pass_motion, reject_motion

    check_sorting_motors(controller)
    if inspection.is_pass:
        return pass_motion.run(controller, inspection)
    return reject_motion.run(controller, inspection)


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
        # 중단 버튼과 종료 처리가 워커 스레드의 컨트롤러를 건드려야 한다.
        self._motion_controller: OmxController | None = None
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

        self.stop_button = ttk.Button(
            self, text="동작 중단", command=self.stop_motion, state="disabled"
        )
        self.stop_button.grid(row=5, column=0, sticky="ew", pady=(6, 2))

        self.status_var = tk.StringVar(value="대기")
        ttk.Label(self, textvariable=self.status_var, anchor="w", wraplength=210).grid(
            row=6, column=0, sticky="ew", pady=(6, 0)
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

    def set_external_busy(self, busy: bool) -> None:
        """통합 공정이 OMX2를 소유하는 동안 수동 분류 버튼을 잠근다."""
        if self.is_busy():
            return
        state = "disabled" if busy else "normal"
        for button in (self.teach_button, self.pass_button, self.reject_button):
            button.configure(state=state)
        self.stop_button.configure(state="disabled")

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
        # 컨트롤러는 메인 스레드에서 만들어 둔다. 그래야 워커가 연결을 잡기
        # 전에 중단 버튼을 눌러도 요청이 전달된다.
        controller = OmxController(OmxConfig(port=port))
        self._motion_controller = controller
        self._on_tool_start(TOOL_MOTION)
        self._set_motion_buttons(enabled=False)
        self.status_var.set(f"{motion} 동작 실행 중...")
        self._motion_thread = threading.Thread(
            target=self._motion_worker, args=(motion, controller), daemon=True
        )
        self._motion_thread.start()

    def stop_motion(self) -> None:
        """실행 중인 동작에 중단을 요청한다. 워커는 다음 확인 지점에서 멈춘다."""
        controller = self._motion_controller
        if controller is None:
            return
        controller.request_stop()
        self.stop_button.configure(state="disabled")
        self.status_var.set("중단 요청됨 — 정지 중...")

    def _motion_worker(self, motion: str, controller: OmxController) -> None:
        try:
            controller.connect()
            inspection = MANUAL_PASS if motion == "PASS" else MANUAL_REJECT
            status = execute_sorting_motion(controller, inspection)
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
        self._motion_controller = None
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
        # 중단 버튼만 반대로 움직인다 — 동작 중일 때만 누를 수 있다.
        self.stop_button.configure(state="disabled" if enabled else "normal")

    # ------------------------------------------------------------------ 종료

    def request_close(self) -> bool:
        """대시보드 종료 직전에 부른다. 닫아도 되면 True.

        동작 중이라도 사용자가 원하면 중단하고 닫는다. 예전에는 무조건
        거부해서, 응답 없는 포트에 붙어 12스텝을 헛도는 동안 창을 닫지
        못하고 터미널에서 Ctrl+C를 눌러야 했다.
        """
        if self._motion_thread is not None and self._motion_thread.is_alive():
            if not messagebox.askyesno(
                "분류 동작 실행 중",
                "분류 동작이 아직 실행 중입니다.\n"
                "중단하고 종료할까요?\n\n"
                "주의: 팔이 움직이는 중이면 토크가 풀리며 자세가 흐트러질 수 있습니다.",
                parent=self.root,
                default=messagebox.NO,
            ):
                return False
            if self._motion_controller is not None:
                self._motion_controller.request_stop()
            # 워커는 daemon 스레드라 프로세스가 끝나면 같이 죽는다. 그래도
            # 잠깐 기다려 주면 토크 해제와 포트 닫기까지 정상적으로 끝난다.
            self._motion_thread.join(timeout=MOTION_STOP_TIMEOUT_SEC)
        if self._teach_window is not None and self._teach_window.winfo_exists():
            # 교시 창의 토크 경고 흐름을 그대로 태운다.
            self._teach_window._on_close()
            if self._teach_window is not None:
                return False
        return True
