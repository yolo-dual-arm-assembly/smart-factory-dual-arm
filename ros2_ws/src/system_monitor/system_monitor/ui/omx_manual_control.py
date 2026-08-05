"""ROBOTIS OMX 관절 제어 GUI (Tkinter 기반).

5개 관절 angle과 그리퍼를 슬라이더로 직접 조정하며
실제 로봇팔을 실시간 조종하고 각도/위치값을 확인할 수 있습니다.
"""
from __future__ import annotations

import math
import argparse
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Optional

# OMX 패널이 이 파일을 별도 프로세스로 띄우고, VS Code의 "Run Python File"로도
# 직접 실행한다. 그때 sys.path에는 이 파일이 있는 ui 디렉터리만 들어가므로,
# 패키지 루트(system_monitor)와 common 패키지 루트를 직접 추가해
# 모듈 실행(`python -m system_monitor.ui.omx_manual_control`)과 같게 만든다.
if __package__ in (None, ""):
    _here = Path(__file__).resolve()
    _workspace_src = _here.parents[3]  # ros2_ws/src
    sys.path.insert(0, str(_workspace_src / "system_monitor"))
    sys.path.insert(0, str(_workspace_src / "common"))

from common.omx_controller import (
    HOME_MOVE_DURATION,
    HOME_ANGLES,
    GRIPPER_OPEN_POS,
    JOINT_LIMITS,
    OmxConfig,
    OmxController,
    angle_to_dxl,
    dxl_to_angle,
    gripper_percent_to_dxl,
)
from common.serial_ports import default_omx_port
from system_monitor.ui.ui_fonts import configure_korean_fonts


class OmxGuiApp(tk.Tk):
    def __init__(self, port: str | None = None) -> None:
        super().__init__()
        port = port or default_omx_port()
        configure_korean_fonts(self)
        self.title("ROBOTIS OMX Joint Controller")
        self.geometry("640x580")
        self.resizable(False, False)

        self.port = port
        self.config = OmxConfig(port=port)
        self.controller: Optional[OmxController] = None
        self.is_connected = False
        self._updating_home_ui = False
        self._home_in_progress = False
        # 홈 복귀가 끝나기를 기다리는 중인 종료 요청. _finish_home_move가 마무리한다.
        self._closing = False
        self._disabled_widget_states: list[tuple[tk.Widget, str]] = []

        self.joint_entries: list[ttk.Entry] = []
        self.joint_vars: list[tk.DoubleVar] = []
        self.dxl_labels: list[ttk.Label] = []

        # 그리퍼 변수
        self.gripper_var = tk.DoubleVar(value=0)  # 0: Open, 100: Closed

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        # 상단 연결 프레임
        top_frame = ttk.LabelFrame(self, text=" 통신 연결 ", padding=10)
        top_frame.pack(fill="x", padx=10, pady=5)

        ttk.Label(top_frame, text="시리얼 포트:").pack(side="left", padx=5)
        self.port_entry = ttk.Entry(top_frame, width=15)
        self.port_entry.insert(0, self.port)
        self.port_entry.pack(side="left", padx=5)

        self.btn_connect = ttk.Button(
            top_frame, text="로봇 연결 (Connect)", command=self._toggle_connection
        )
        self.btn_connect.pack(side="left", padx=10)

        self.lbl_status = ttk.Label(
            top_frame, text="상태: 연결 안 됨", foreground="red"
        )
        self.lbl_status.pack(side="left", padx=10)

        # 관절 조절 프레임
        joint_frame = ttk.LabelFrame(self, text=" 관절 각도 제어 (Joint Control) ", padding=10)
        joint_frame.pack(fill="both", expand=True, padx=10, pady=5)

        joint_names = [
            "Joint 1 (베이스 회전)",
            "Joint 2 (어깨)",
            "Joint 3 (팔꿈치)",
            "Joint 4 (손목 pitch)",
            "Joint 5 (손목 roll)",
        ]

        for i, name in enumerate(joint_names):
            min_rad, max_rad = JOINT_LIMITS[i]
            min_deg = round(math.degrees(min_rad), 1)
            max_deg = round(math.degrees(max_rad), 1)
            home_deg = round(math.degrees(HOME_ANGLES[i]), 1)

            row_frame = ttk.Frame(joint_frame)
            row_frame.pack(fill="x", pady=6)

            # 라벨
            lbl_name = ttk.Label(row_frame, text=f"J{i+1}: {name}", width=20, anchor="w")
            lbl_name.pack(side="left", padx=5)

            # 슬라이더
            var = tk.DoubleVar(value=home_deg)
            self.joint_vars.append(var)

            slider = ttk.Scale(
                row_frame,
                from_=min_deg,
                to=max_deg,
                variable=var,
                orient="horizontal",
                command=lambda val, idx=i: self._on_slider_move(idx, val),
            )
            slider.pack(side="left", fill="x", expand=True, padx=5)

            # 각도 입력창 (Entry)
            entry = ttk.Entry(row_frame, width=7, justify="right")
            entry.insert(0, f"{home_deg:.1f}")
            entry.pack(side="left", padx=2)
            entry.bind("<Return>", lambda evt, idx=i: self._on_entry_commit(idx))
            entry.bind("<FocusOut>", lambda evt, idx=i: self._on_entry_commit(idx))
            self.joint_entries.append(entry)

            ttk.Label(row_frame, text="°").pack(side="left", padx=(0, 5))

            # DXL 값 표시 라벨
            dxl_init = angle_to_dxl(HOME_ANGLES[i])
            lbl_dxl = ttk.Label(row_frame, text=f"(DXL: {dxl_init:4d})", width=12, anchor="e")
            lbl_dxl.pack(side="left", padx=5)
            self.dxl_labels.append(lbl_dxl)

        # 그리퍼 제어 프레임
        grip_frame = ttk.LabelFrame(self, text=" 그리퍼 제어 (Gripper Control) ", padding=10)
        grip_frame.pack(fill="x", padx=10, pady=5)

        grip_row = ttk.Frame(grip_frame)
        grip_row.pack(fill="x", pady=4)

        ttk.Label(grip_row, text="Gripper (집게):", width=20, anchor="w").pack(side="left", padx=5)

        # 0: 완전 열림, 100: 완전 닫힘
        grip_slider = ttk.Scale(
            grip_row,
            from_=0,
            to=100,
            variable=self.gripper_var,
            orient="horizontal",
            command=self._on_gripper_slider_move,
        )
        grip_slider.pack(side="left", fill="x", expand=True, padx=5)

        # 그리퍼 퍼센트 입력창
        self.grip_entry = ttk.Entry(grip_row, width=7, justify="right")
        self.grip_entry.insert(0, "0.0")
        self.grip_entry.pack(side="left", padx=2)
        self.grip_entry.bind("<Return>", lambda evt: self._on_grip_entry_commit())
        self.grip_entry.bind("<FocusOut>", lambda evt: self._on_grip_entry_commit())

        ttk.Label(grip_row, text="%").pack(side="left", padx=(0, 5))

        self.lbl_grip_dxl = ttk.Label(
            grip_row,
            text=f"(DXL: {GRIPPER_OPEN_POS})",
            width=12,
            anchor="e",
        )
        self.lbl_grip_dxl.pack(side="left", padx=5)

        btn_row = ttk.Frame(grip_frame)
        btn_row.pack(fill="x", pady=4)

        btn_open = ttk.Button(btn_row, text="완전 열기 (Open 0%)", command=self._open_gripper)
        btn_open.pack(side="left", padx=5)

        btn_close = ttk.Button(btn_row, text="완전 닫기 (Close 100%)", command=self._close_gripper)
        btn_close.pack(side="left", padx=5)

        # 하단 조작 버튼
        cmd_frame = ttk.Frame(self, padding=10)
        cmd_frame.pack(fill="x", padx=10, pady=5)

        ttk.Button(cmd_frame, text="홈 포즈 (Home Pose)", command=self._go_home).pack(
            side="left", padx=5
        )
        ttk.Button(cmd_frame, text="토크 OFF (Relax)", command=self._disable_torque).pack(
            side="left", padx=5
        )
        ttk.Button(cmd_frame, text="토크 ON (Lock)", command=self._enable_torque).pack(
            side="left", padx=5
        )

    def _toggle_connection(self) -> None:
        if self.is_connected:
            self._disconnect_robot()
        else:
            self._connect_robot()

    def _connect_robot(self) -> None:
        port = self.port_entry.get().strip()
        self.config.port = port
        self.controller = OmxController(self.config)
        try:
            self.controller.connect()
            self.is_connected = True
            self.lbl_status.config(text=f"상태: 연결됨 ({port})", foreground="green")
            self.btn_connect.config(text="연결 해제 (Disconnect)")
            # 연결 시 홈 포즈 위치로 맞춤
            self._go_home()
        except Exception as exc:
            messagebox.showerror("연결 오류", f"로봇 연결 실패:\n{exc}")
            self.controller = None
            self.is_connected = False

    def _disconnect_robot(self) -> None:
        if self.controller:
            try:
                self.controller.disconnect()
            except Exception:
                pass
        self.controller = None
        self.is_connected = False
        self.lbl_status.config(text="상태: 연결 안 됨", foreground="red")
        self.btn_connect.config(text="로봇 연결 (Connect)")

    def _on_slider_move(self, idx: int, value: str) -> None:
        deg = float(value)
        rad = math.radians(deg)
        dxl_val = angle_to_dxl(rad)

        # Entry text 갱신 (포커스가 없을 때만)
        if self.focus_get() != self.joint_entries[idx]:
            self.joint_entries[idx].delete(0, tk.END)
            self.joint_entries[idx].insert(0, f"{deg:.1f}")

        self.dxl_labels[idx].config(text=f"(DXL: {dxl_val:4d})")

        # 연결된 상태면 로봇으로 실시간 각도 전송
        if (
            not self._updating_home_ui
            and self.is_connected
            and self.controller
        ):
            angles = [math.radians(v.get()) for v in self.joint_vars]
            try:
                self.controller.move_joints(angles, duration=0.05)
            except Exception as e:
                print(f"[GUI] 이동 명령어 전송 에러: {e}")

    def _on_entry_commit(self, idx: int) -> None:
        try:
            val_str = self.joint_entries[idx].get().strip()
            deg = float(val_str)
            min_rad, max_rad = JOINT_LIMITS[idx]
            min_deg, max_deg = math.degrees(min_rad), math.degrees(max_rad)
            deg_clamped = max(min_deg, min(max_deg, deg))

            self.joint_vars[idx].set(deg_clamped)
            self._on_slider_move(idx, str(deg_clamped))
        except ValueError:
            pass

    def _on_gripper_slider_move(self, value: str) -> None:
        percent = float(value)
        dxl_pos = gripper_percent_to_dxl(percent)

        if self.focus_get() != self.grip_entry:
            self.grip_entry.delete(0, tk.END)
            self.grip_entry.insert(0, f"{percent:.1f}")

        self.lbl_grip_dxl.config(text=f"(DXL: {dxl_pos:4d})")

        if self.is_connected and self.controller:
            try:
                self.controller.set_gripper_position(dxl_pos)
            except Exception as e:
                print(f"[GUI] 그리퍼 제어 오류: {e}")

    def _on_grip_entry_commit(self) -> None:
        try:
            val_str = self.grip_entry.get().strip()
            percent = float(val_str)
            percent_clamped = max(0.0, min(100.0, percent))
            self.gripper_var.set(percent_clamped)
            self._on_gripper_slider_move(str(percent_clamped))
        except ValueError:
            pass

    def _go_home(self) -> None:
        if self._home_in_progress:
            return
        if not self.is_connected or not self.controller:
            self._update_joint_display(HOME_ANGLES)
            return

        self._home_in_progress = True
        self._set_controls_enabled(False)
        controller = self.controller

        def report_progress(angles: list[float]) -> None:
            self.after(0, self._update_joint_display, angles)

        def move_home() -> None:
            error: Optional[Exception] = None
            try:
                controller.move_joints_smooth(
                    HOME_ANGLES,
                    duration=HOME_MOVE_DURATION,
                    progress_callback=report_progress,
                )
            except Exception as exc:
                error = exc
            self.after(0, self._finish_home_move, error)

        threading.Thread(target=move_home, daemon=True).start()

    def _update_joint_display(self, angles: list[float]) -> None:
        """홈 이동 중 관절 슬라이더와 표시값을 한 단계 갱신한다."""
        self._updating_home_ui = True
        try:
            for i, rad in enumerate(angles):
                deg = math.degrees(rad)
                self.joint_vars[i].set(deg)
                self.joint_entries[i].delete(0, tk.END)
                self.joint_entries[i].insert(0, f"{deg:.1f}")
                self.dxl_labels[i].config(
                    text=f"(DXL: {angle_to_dxl(rad):4d})"
                )
        finally:
            self._updating_home_ui = False

    def _set_controls_enabled(self, enabled: bool) -> None:
        """홈 이동 중 모든 조작 위젯을 잠그고 완료 후 원래 상태로 복구한다."""
        widget_types = (ttk.Button, ttk.Entry, ttk.Scale)
        if not enabled:
            self._disabled_widget_states.clear()
            pending = list(self.winfo_children())
            while pending:
                widget = pending.pop()
                pending.extend(widget.winfo_children())
                if isinstance(widget, widget_types):
                    state = str(widget.cget("state"))
                    self._disabled_widget_states.append((widget, state))
                    widget.configure(state="disabled")
            return

        for widget, state in self._disabled_widget_states:
            if widget.winfo_exists():
                widget.configure(state=state)
        self._disabled_widget_states.clear()

    def _finish_home_move(self, error: Optional[Exception]) -> None:
        self._home_in_progress = False
        self._set_controls_enabled(True)
        if error is not None:
            messagebox.showerror("홈 이동 오류", f"홈 포즈 이동 실패:\n{error}")
        if self._closing:
            # 홈 복귀를 기다리려고 미뤄 둔 종료를 이제 마무리한다.
            self._closing = False
            self._disconnect_robot()
            self.destroy()

    def _open_gripper(self) -> None:
        self.gripper_var.set(0)
        self._on_gripper_slider_move("0")

    def _close_gripper(self) -> None:
        self.gripper_var.set(100)
        self._on_gripper_slider_move("100")

    def _enable_torque(self) -> None:
        if self.is_connected and self.controller:
            self.controller.enable_torque()

    def _disable_torque(self) -> None:
        if self.is_connected and self.controller:
            self.controller.disable_torque()

    def _on_close(self) -> None:
        if self._home_in_progress:
            messagebox.showinfo(
                "홈 이동 중",
                "홈 포즈 이동이 끝난 뒤 창을 닫아 주세요.",
            )
            return
        # disconnect()는 전 관절 토크를 끊는다. 팔이 뻗은 자세에서 그대로
        # 끊으면 중력으로 떨어지므로 홈 자세로 접은 뒤에 끊는다.
        if self.is_connected and self.controller:
            self._closing = True
            self.lbl_status.config(
                text="상태: 홈 복귀 후 종료 중...", foreground="blue"
            )
            self._go_home()
            return
        self.destroy()


def main() -> None:
    parser = argparse.ArgumentParser(description="ROBOTIS OMX 수동 관절 제어 GUI")
    parser.add_argument(
        "--port",
        default=default_omx_port(),
        help="OMX 시리얼 포트 (기본: 연결된 USB 시리얼 포트 자동 선택)",
    )
    args = parser.parse_args()
    app = OmxGuiApp(port=args.port)
    app.mainloop()


if __name__ == "__main__":
    main()
