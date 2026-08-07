"""운영 대시보드에 쓰는 장치 상태 카드와 영상 패널.

위젯은 상태를 스스로 만들지 않는다. ``ArmSnapshot``·``CameraSnapshot``을 받아
그리기만 하므로, 장치나 스레드 없이도 화면 구성을 확인할 수 있다.
"""
from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk
from typing import Callable

import cv2
from PIL import Image, ImageTk

from common.constants import RobotState
from common.messages import InspectionResult
from system_monitor.ui.arm_monitor import ArmSnapshot
from system_monitor.ui.camera_feed import CameraSnapshot

# 연결 표시등. 색 없이도 구분되도록 기호를 함께 쓴다.
LAMP_ON = "●"
LAMP_OFF = "○"
COLOR_OK = "#1a7f37"
COLOR_IDLE = "#57606a"
COLOR_WARN = "#9a6700"
COLOR_ERROR = "#cf222e"

PASS_COLOR = "#1a7f37"
REJECT_COLOR = "#cf222e"

# 영상 라벨의 relief 테두리에 그림이 가리지 않도록 빼 두는 여백(픽셀).
VIDEO_PADDING = 6
# 위젯이 아직 배치되기 전에는 winfo_width()가 1을 준다. 그보다 작으면 맞추지 않는다.
MIN_FIT_SIZE = 40

# 바구니 하나에 들어갈 수 있는 공 개수의 상한. 실수로 큰 값을 넣는 것을 막는 정도의
# 안전장치라 넉넉히 잡는다.
MAX_TARGET_COUNT = 50


def _lamp(connected: bool, released: bool) -> tuple[str, str]:
    if released:
        return LAMP_OFF, COLOR_WARN
    if connected:
        return LAMP_ON, COLOR_OK
    return LAMP_OFF, COLOR_IDLE


class ArmStatusCard(ttk.LabelFrame):
    """로봇팔 한 대의 연결·상태·관절각·좌표를 보여 준다."""

    def __init__(
        self,
        master: tk.Misc,
        title: str,
        *,
        description: str = "",
        joint_count: int = 5,
    ) -> None:
        super().__init__(master, text=title, padding=8)
        self.columnconfigure(1, weight=1)

        self.lamp_var = tk.StringVar(value=LAMP_OFF)
        self.lamp = ttk.Label(self, textvariable=self.lamp_var, foreground=COLOR_IDLE)
        self.lamp.grid(row=0, column=0, sticky="w")

        self.status_var = tk.StringVar(value="준비 중...")
        ttk.Label(self, textvariable=self.status_var, anchor="w").grid(
            row=0, column=1, sticky="ew", padx=(4, 0)
        )

        self.port_var = tk.StringVar(value="포트 --")
        ttk.Label(
            self, textvariable=self.port_var, anchor="w", foreground=COLOR_IDLE
        ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(2, 0))

        self.joint_vars = [tk.StringVar(value=f"J{i + 1} --") for i in range(joint_count)]
        joints = ttk.Frame(self)
        joints.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        for index, var in enumerate(self.joint_vars):
            joints.columnconfigure(index, weight=1)
            ttk.Label(joints, textvariable=var, anchor="w", font="TkFixedFont").grid(
                row=0, column=index, sticky="ew"
            )

        self.position_var = tk.StringVar(value="XYZ --")
        ttk.Label(
            self, textvariable=self.position_var, anchor="w", font="TkFixedFont"
        ).grid(row=3, column=0, columnspan=2, sticky="ew", pady=(4, 0))

        if description:
            ttk.Label(
                self, text=description, anchor="w", foreground=COLOR_IDLE
            ).grid(row=4, column=0, columnspan=2, sticky="ew", pady=(4, 0))

    def update_from(self, snapshot: ArmSnapshot) -> None:
        symbol, color = _lamp(snapshot.connected, snapshot.released)
        self.lamp_var.set(symbol)
        self.lamp.configure(foreground=color)
        self.status_var.set(snapshot.status_text)
        self.port_var.set(f"포트 {snapshot.port or '--'}")

        for index, var in enumerate(self.joint_vars):
            if index < len(snapshot.angles):
                var.set(f"J{index + 1} {math.degrees(snapshot.angles[index]):6.1f}°")
            else:
                var.set(f"J{index + 1} --")

        if snapshot.position is None:
            self.position_var.set("XYZ --")
        else:
            x, y, z = snapshot.position
            self.position_var.set(
                f"XYZ {x * 100:6.1f}, {y * 100:6.1f}, {z * 100:6.1f} cm"
            )


class CameraStatusCard(ttk.LabelFrame):
    """카메라 한 대의 연결·장치·FPS를 보여 준다."""

    def __init__(
        self, master: tk.Misc, title: str, *, description: str = ""
    ) -> None:
        super().__init__(master, text=title, padding=8)
        self.columnconfigure(1, weight=1)

        self.lamp_var = tk.StringVar(value=LAMP_OFF)
        self.lamp = ttk.Label(self, textvariable=self.lamp_var, foreground=COLOR_IDLE)
        self.lamp.grid(row=0, column=0, sticky="w")

        self.status_var = tk.StringVar(value="준비 중...")
        ttk.Label(self, textvariable=self.status_var, anchor="w").grid(
            row=0, column=1, sticky="ew", padx=(4, 0)
        )

        self.device_var = tk.StringVar(value="장치 --")
        ttk.Label(
            self, textvariable=self.device_var, anchor="w", foreground=COLOR_IDLE
        ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(2, 0))

        self.detail_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.detail_var, anchor="w").grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=(4, 0)
        )

        if description:
            ttk.Label(
                self, text=description, anchor="w", foreground=COLOR_IDLE
            ).grid(row=3, column=0, columnspan=2, sticky="ew", pady=(4, 0))

    def update_from(self, snapshot: CameraSnapshot) -> None:
        symbol, color = _lamp(snapshot.connected, snapshot.released)
        self.lamp_var.set(symbol)
        self.lamp.configure(foreground=color)
        self.status_var.set(snapshot.status_text)

        if snapshot.index is None:
            self.device_var.set("장치 --")
        elif snapshot.name:
            self.device_var.set(f"장치 {snapshot.index}번 · {snapshot.name}")
        else:
            self.device_var.set(f"장치 {snapshot.index}번")

        if snapshot.connected and snapshot.infer_fps > 0:
            self.detail_var.set(f"탐지 {snapshot.detection_count}개")
        else:
            self.detail_var.set("")


class VideoPanel(ttk.LabelFrame):
    """카메라 영상 하나를 그리는 패널."""

    def __init__(self, master: tk.Misc, title: str, *, idle_text: str) -> None:
        super().__init__(master, text=title, padding=6)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self._idle_text = idle_text
        # Tk PhotoImage는 파이썬 참조가 사라지면 GC되어 화면에서 지워진다.
        self._photo: ImageTk.PhotoImage | None = None

        self.video_label = ttk.Label(
            self, text=idle_text, anchor="center", relief="solid"
        )
        self.video_label.grid(row=0, column=0, sticky="nsew")

        self.caption_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.caption_var, anchor="w").grid(
            row=1, column=0, sticky="ew", pady=(4, 0)
        )

    def show_frame(self, frame) -> None:
        """BGR 프레임을 패널 크기에 맞춰 그린다.

        카메라마다 가로세로 비율이 다르므로(4:3, 16:9 ...) 고정 크기로 그리면
        위아래가 남거나 잘린다. 지금 패널에 들어갈 수 있는 최대 크기로 비율을
        유지한 채 맞춘다. 프레임의 실제 shape을 쓰므로 화면 비율은 언제나
        카메라가 실제로 내보내는 비율과 같다.
        """
        frame = self._fit_to_panel(frame)
        image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        # 같은 크기면 기존 PhotoImage에 제자리 갱신하는 쪽이 훨씬 싸다.
        if (
            self._photo is not None
            and self._photo.width() == image.width
            and self._photo.height() == image.height
        ):
            self._photo.paste(image)
        else:
            self._photo = ImageTk.PhotoImage(image)
            self.video_label.configure(image=self._photo, text="")

    def _fit_to_panel(self, frame):
        """비율을 유지한 채 지금 패널에 꽉 차게 크기를 맞춘다."""
        height, width = frame.shape[:2]
        if width < 1 or height < 1:
            return frame
        # relief 테두리에 가려지지 않도록 몇 픽셀 뺀다.
        available_width = self.video_label.winfo_width() - VIDEO_PADDING
        available_height = self.video_label.winfo_height() - VIDEO_PADDING
        # 아직 배치 전이면 winfo_*가 1을 준다. 그때는 원본 그대로 둔다.
        if available_width < MIN_FIT_SIZE or available_height < MIN_FIT_SIZE:
            return frame

        scale = min(available_width / width, available_height / height)
        target = (max(round(width * scale), 1), max(round(height * scale), 1))
        if target == (width, height):
            return frame
        interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
        return cv2.resize(frame, target, interpolation=interpolation)

    def show_message(self, message: str) -> None:
        """영상 대신 안내 문구를 보여 준다."""
        self._photo = None
        self.video_label.configure(image="", text=message or self._idle_text)

    def set_caption(self, text: str) -> None:
        self.caption_var.set(text)


class InspectionResultBar(ttk.Frame):
    """검수 캠의 최신 판정을 한 줄로 보여 주고, 기준 개수를 바꾸게 한다."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        font_family: str = "TkDefaultFont",
        target_count: int = 1,
        on_target_change: Callable[[int], None] | None = None,
    ) -> None:
        super().__init__(master, padding=(10, 6))
        self.columnconfigure(1, weight=1)

        self._on_target_change = on_target_change or (lambda _value: None)
        self._applied_target = target_count

        ttk.Label(self, text="검사 결과").grid(row=0, column=0, sticky="w")

        self.verdict_var = tk.StringVar(value="대기 중")
        self.verdict_label = ttk.Label(
            self,
            textvariable=self.verdict_var,
            font=(font_family, 13, "bold"),
            anchor="w",
        )
        self.verdict_label.grid(row=0, column=1, sticky="w", padx=(10, 0))

        # 기준 개수는 운영 중에만 바꾼다. 설정 파일에는 쓰지 않으므로 프로그램을
        # 다시 켜면 파일 값으로 돌아간다.
        target_box = ttk.Frame(self)
        target_box.grid(row=0, column=3, sticky="e", padx=(10, 12))
        ttk.Label(target_box, text="기준 개수").grid(row=0, column=0, sticky="e")
        self.target_var = tk.StringVar(value=str(target_count))
        self.target_spin = ttk.Spinbox(
            target_box,
            from_=0,
            to=MAX_TARGET_COUNT,
            width=4,
            justify="right",
            textvariable=self.target_var,
            command=self._apply_target,
        )
        self.target_spin.grid(row=0, column=1, sticky="e", padx=(4, 0))
        # 화살표뿐 아니라 직접 입력한 값도 반영한다.
        self.target_spin.bind("<Return>", self._apply_target)
        self.target_spin.bind("<FocusOut>", self._apply_target)

        # 바구니가 흔들려 개수가 확정되지 않은 동안 띄우는 표시. 확정 판정은
        # 래치되어 그대로 남고, 이 라벨만 나타났다 사라진다.
        self.settling_var = tk.StringVar(value="")
        ttk.Label(
            self, textvariable=self.settling_var, anchor="w", foreground=COLOR_WARN
        ).grid(row=0, column=2, sticky="w")

        self.detail_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.detail_var, anchor="e").grid(
            row=0, column=4, sticky="e"
        )

    def _apply_target(self, _event: object = None) -> None:
        """입력값을 검사해 반영한다. 숫자가 아니면 직전 값으로 되돌린다."""
        try:
            value = int(self.target_var.get())
        except ValueError:
            self.target_var.set(str(self._applied_target))
            return
        value = max(0, min(MAX_TARGET_COUNT, value))
        # 잘린 값이 있으면 화면도 맞춰 준다.
        self.target_var.set(str(value))
        if value == self._applied_target:
            return
        self._applied_target = value
        self._on_target_change(value)

    def update_from(
        self, result: InspectionResult | None, *, settling: bool = False
    ) -> None:
        """확정 판정과 안정화 상태를 화면에 반영한다.

        ``result``는 안정화 게이트가 래치한 **확정** 판정이다. 흔들리는 동안에도
        지워지지 않고, 대신 ``settling`` 표시가 옆에 나타난다.
        """
        self.settling_var.set("안정화 중…" if settling else "")
        if result is None:
            self.verdict_var.set("대기 중")
            self.verdict_label.configure(foreground=COLOR_IDLE)
            self.detail_var.set("")
            return
        self.verdict_var.set(str(result.result))
        self.verdict_label.configure(
            foreground=PASS_COLOR if result.result is RobotState.PASS else REJECT_COLOR
        )
        # total_count에는 공(ball)만 세고 오투입(others)은 defect_count로
        # 넘어온다. 화면의 '총'은 검출된 물체 전체(ball+others)를 보여준다.
        self.detail_var.set(
            f"총 {result.total_count + result.defect_count}개 · "
            f"정상 {result.total_count} · 불량 {result.defect_count}"
        )
