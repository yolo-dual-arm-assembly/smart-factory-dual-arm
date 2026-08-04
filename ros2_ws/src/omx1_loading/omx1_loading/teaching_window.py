"""YOLO Mouse 탐지 위치와 OMX 실제 관절 자세를 함께 저장하는 교시 GUI."""
from __future__ import annotations

import math
import threading
import time
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable

import cv2
import numpy as np
from PIL import Image, ImageTk
from ultralytics import YOLO

from common.camera import open_camera
from common.omx_controller import (
    HOME_ANGLES,
    JOINT_LIMITS,
    OmxConfig,
    OmxController,
    angle_to_dxl,
)
from omx1_loading.teaching import MIN_TEACHING_POINTS, OmxTeachingDataset
from system_monitor.ui.ui_fonts import configure_korean_fonts


TEACHING_PREVIEW_SIZE = (820, 620)
TEACHING_POLL_MS = 30


class OmxTeachingWindow(tk.Toplevel):
    """한 창에서 Mouse를 보면서 관절을 조작하고 현재 자세를 교시한다."""

    def __init__(
        self,
        master: tk.Misc,
        model_path: Path,
        teaching_path: Path,
        port: str,
        camera_index: int,
        on_changed: Callable[[], None] | None = None,
        on_closed: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(master)
        self.ui_font_family, _ = configure_korean_fonts(self)
        self.title("OMX Mouse 관절 교시")
        self.geometry("1420x820")
        self.minsize(1100, 700)

        self.model_path = model_path
        self.teaching_path = teaching_path
        self.camera_index = camera_index
        self.on_changed = on_changed
        self.on_closed = on_closed
        self.controller = OmxController(OmxConfig(port=port))
        self.dataset = (
            OmxTeachingDataset.load(teaching_path)
            if teaching_path.is_file()
            else OmxTeachingDataset()
        )

        self._lock = threading.Lock()
        self._latest = None
        self._target = None
        self._locked_target = None
        self._error: str | None = None
        self._stop_event = threading.Event()
        self._photo: ImageTk.PhotoImage | None = None
        self._connected = False
        self._moving = False
        self._updating_joint_ui = False
        self._slider_after_id: str | None = None

        self.joint_vars: list[tk.DoubleVar] = []
        self.joint_value_vars: list[tk.StringVar] = []
        self.target_var = tk.StringVar(value="Mouse 탐지 대기 중")
        self.status_var = tk.StringVar(value="로봇 연결 전")
        self.count_var = tk.StringVar()

        self._build_ui()
        self._update_count()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self._camera_thread = threading.Thread(target=self._camera_worker, daemon=True)
        self._camera_thread.start()
        self.after(TEACHING_POLL_MS, self._poll_frame)

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=0)
        self.rowconfigure(0, weight=1)

        camera_panel = ttk.LabelFrame(self, text="YOLO Mouse 탐지", padding=8)
        camera_panel.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        camera_panel.columnconfigure(0, weight=1)
        camera_panel.rowconfigure(0, weight=1)
        self.preview = ttk.Label(
            camera_panel, text="카메라와 모델 준비 중...", anchor="center", relief="solid"
        )
        self.preview.grid(row=0, column=0, sticky="nsew")
        ttk.Label(
            camera_panel,
            textvariable=self.target_var,
            font=(self.ui_font_family, 12, "bold"),
        ).grid(row=1, column=0, sticky="w", pady=(8, 0))

        controls = ttk.LabelFrame(self, text="OMX 수동 관절 교시", padding=10)
        controls.grid(row=0, column=1, sticky="ns", padx=(0, 10), pady=10)
        controls.columnconfigure(1, weight=1)

        for index, (angle, (lower, upper)) in enumerate(
            zip(HOME_ANGLES, JOINT_LIMITS)
        ):
            ttk.Label(controls, text=f"J{index + 1}", width=4).grid(
                row=index, column=0, sticky="w", pady=7
            )
            variable = tk.DoubleVar(value=math.degrees(angle))
            self.joint_vars.append(variable)
            slider = ttk.Scale(
                controls,
                from_=math.degrees(lower),
                to=math.degrees(upper),
                variable=variable,
                command=lambda _value, idx=index: self._on_slider_changed(idx),
                length=300,
                state="disabled",
            )
            slider.grid(row=index, column=1, sticky="ew", padx=6)
            setattr(self, f"joint_slider_{index}", slider)
            value_var = tk.StringVar()
            self.joint_value_vars.append(value_var)
            ttk.Label(controls, textvariable=value_var, width=18).grid(
                row=index, column=2, sticky="e"
            )
            self._set_joint_text(index, math.degrees(angle))

        separator_row = len(self.joint_vars)
        ttk.Separator(controls).grid(
            row=separator_row, column=0, columnspan=3, sticky="ew", pady=10
        )

        self.connect_button = ttk.Button(
            controls, text="로봇 연결", command=self._toggle_connection
        )
        self.connect_button.grid(
            row=separator_row + 1, column=0, columnspan=2, sticky="ew", padx=(0, 4)
        )
        self.home_button = ttk.Button(
            controls, text="홈", command=self._go_home, state="disabled"
        )
        self.home_button.grid(
            row=separator_row + 1, column=2, sticky="ew", padx=(4, 0)
        )

        self.lock_target_button = ttk.Button(
            controls,
            text="1. Mouse 위치 고정",
            command=self._toggle_target_lock,
            state="disabled",
        )
        self.lock_target_button.grid(
            row=separator_row + 2,
            column=0,
            columnspan=3,
            sticky="ew",
            pady=(10, 0),
        )

        self.save_button = ttk.Button(
            controls,
            text="2. 고정 위치 + 실제 관절값 저장",
            command=self._save_teaching_point,
            state="disabled",
        )
        self.save_button.grid(
            row=separator_row + 3,
            column=0,
            columnspan=3,
            sticky="ew",
            pady=(6, 0),
        )
        ttk.Button(
            controls, text="마지막 교시점 삭제", command=self._remove_last_point
        ).grid(
            row=separator_row + 4,
            column=0,
            columnspan=3,
            sticky="ew",
            pady=(6, 0),
        )

        ttk.Label(
            controls,
            textvariable=self.count_var,
            font=(self.ui_font_family, 11, "bold"),
        ).grid(
            row=separator_row + 5,
            column=0,
            columnspan=3,
            sticky="w",
            pady=(12, 0),
        )
        ttk.Label(
            controls,
            text=(
                "Mouse 위치를 먼저 고정한 뒤 그리퍼를 직접 맞추고 저장하세요.\n"
                "좌상·상·우상 / 좌·중앙·우 / 좌하·하·우하 9점을 권장합니다."
            ),
            foreground="#555555",
            wraplength=390,
        ).grid(
            row=separator_row + 6,
            column=0,
            columnspan=3,
            sticky="w",
            pady=(8, 0),
        )
        ttk.Label(controls, textvariable=self.status_var, wraplength=390).grid(
            row=separator_row + 7,
            column=0,
            columnspan=3,
            sticky="w",
            pady=(12, 0),
        )

    def _camera_worker(self) -> None:
        capture = None
        try:
            capture = open_camera(self.camera_index)
            model = YOLO(str(self.model_path))
            mouse_ids = [key for key, name in model.names.items() if name == "mouse"]
            if not mouse_ids:
                raise RuntimeError("선택한 YOLO 모델에 mouse 클래스가 없습니다.")

            while not self._stop_event.is_set():
                grabbed, frame = capture.read()
                if not grabbed:
                    raise RuntimeError("교시 카메라 프레임을 읽지 못했습니다.")
                result = model(
                    frame,
                    conf=0.5,
                    classes=mouse_ids,
                    verbose=False,
                )[0]
                target = None
                best_confidence = 0.0
                if result.boxes is not None:
                    for box in result.boxes:
                        confidence = float(box.conf)
                        if confidence <= best_confidence:
                            continue
                        x1, y1, x2, y2 = box.xyxy[0]
                        target = (
                            float((x1 + x2) / 2),
                            float((y1 + y2) / 2),
                            confidence,
                            frame.shape[1],
                            frame.shape[0],
                        )
                        best_confidence = confidence
                annotated = result.plot(img=frame.copy())
                with self._lock:
                    locked_target = self._locked_target
                if locked_target is not None:
                    locked_center = (
                        round(locked_target[0]),
                        round(locked_target[1]),
                    )
                    cv2.drawMarker(
                        annotated,
                        locked_center,
                        (0, 255, 255),
                        markerType=cv2.MARKER_CROSS,
                        markerSize=28,
                        thickness=3,
                    )
                    cv2.putText(
                        annotated,
                        "LOCKED",
                        (locked_center[0] + 16, locked_center[1] + 20),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.65,
                        (0, 255, 255),
                        2,
                    )
                teaching_pixels = [point.pixel for point in self.dataset.points]
                if len(teaching_pixels) >= 3:
                    hull = cv2.convexHull(np.asarray(teaching_pixels, dtype=np.int32))
                    cv2.polylines(annotated, [hull], True, (255, 180, 0), 2)
                for index, (px, py) in enumerate(teaching_pixels, start=1):
                    center = (round(px), round(py))
                    cv2.circle(annotated, center, 6, (255, 180, 0), -1)
                    cv2.putText(
                        annotated,
                        str(index),
                        (center[0] + 8, center[1] - 8),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.55,
                        (255, 180, 0),
                        2,
                    )
                with self._lock:
                    self._latest = annotated
                    self._target = target
        except Exception as error:
            traceback.print_exc()
            with self._lock:
                self._error = str(error)
        finally:
            if capture is not None:
                capture.release()

    def _poll_frame(self) -> None:
        if not self.winfo_exists():
            return
        with self._lock:
            frame, self._latest = self._latest, None
            target = self._target
            locked_target = self._locked_target
            error, self._error = self._error, None
        if error is not None:
            messagebox.showerror("교시 카메라 오류", error, parent=self)
            self.close()
            return
        if frame is not None:
            height, width = frame.shape[:2]
            scale = min(
                TEACHING_PREVIEW_SIZE[0] / width,
                TEACHING_PREVIEW_SIZE[1] / height,
                1.0,
            )
            if scale < 1.0:
                frame = cv2.resize(
                    frame,
                    (round(width * scale), round(height * scale)),
                    interpolation=cv2.INTER_AREA,
                )
            image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            self._photo = ImageTk.PhotoImage(image)
            self.preview.configure(image=self._photo, text="")
        if locked_target is not None:
            cx, cy, confidence, _, _ = locked_target
            self.target_var.set(
                f"고정된 Mouse: ({cx:.0f}, {cy:.0f}) · 신뢰도 {confidence:.2f}"
            )
        elif target is None:
            self.target_var.set("Mouse 탐지 대기 중")
        else:
            cx, cy, confidence, _, _ = target
            self.target_var.set(
                f"Mouse 중심: ({cx:.0f}, {cy:.0f}) · 신뢰도 {confidence:.2f}"
            )
        self._update_target_buttons(target is not None)
        self.after(TEACHING_POLL_MS, self._poll_frame)

    def _toggle_connection(self) -> None:
        if self._connected:
            self.controller.disconnect()
            self._connected = False
            self.connect_button.configure(text="로봇 연결")
            self.status_var.set("로봇 연결 해제됨")
            self._set_joint_controls(False)
            return
        self.connect_button.configure(state="disabled")
        self.status_var.set("로봇 연결 및 현재 관절값 읽는 중...")
        threading.Thread(target=self._connect_worker, daemon=True).start()

    def _connect_worker(self) -> None:
        error = None
        state = None
        try:
            self.controller.connect()
            state = self.controller.read_joint_state(strict=True)
        except Exception as exc:
            error = exc
        self.after(0, self._connection_finished, state, error)

    def _connection_finished(self, state, error: Exception | None) -> None:
        self.connect_button.configure(state="normal")
        if error is not None:
            try:
                self.controller.disconnect()
            except Exception:
                pass
            messagebox.showerror("OMX 연결 오류", str(error), parent=self)
            self.status_var.set("로봇 연결 실패")
            return
        self._connected = True
        self.connect_button.configure(text="연결 해제")
        self.status_var.set("연결됨 · 수동으로 그리퍼를 Mouse 위에 맞추세요.")
        self._set_joint_display(state.angles)
        self._set_joint_controls(True)

    def _set_joint_controls(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for index in range(5):
            getattr(self, f"joint_slider_{index}").configure(state=state)
        self.home_button.configure(state=state)
        self._update_target_buttons(self._target is not None)

    def _toggle_target_lock(self) -> None:
        with self._lock:
            if self._locked_target is not None:
                self._locked_target = None
                locked = False
            elif self._target is not None:
                self._locked_target = self._target
                locked = True
            else:
                return
        self.lock_target_button.configure(
            text="Mouse 위치 다시 감지" if locked else "1. Mouse 위치 고정"
        )
        self.status_var.set(
            "Mouse 위치 고정 완료 · 이제 로봇팔을 해당 위치 위로 맞추세요."
            if locked
            else "위치 고정 해제 · 다음 Mouse를 감지하세요."
        )
        self._update_target_buttons(self._target is not None)

    def _on_slider_changed(self, index: int) -> None:
        degree = self.joint_vars[index].get()
        self._set_joint_text(index, degree)
        if self._updating_joint_ui or not self._connected or self._moving:
            return
        if self._slider_after_id is not None:
            self.after_cancel(self._slider_after_id)
        self._slider_after_id = self.after(60, self._send_slider_targets)

    def _send_slider_targets(self) -> None:
        self._slider_after_id = None
        if not self._connected or self._moving:
            return
        angles = [math.radians(variable.get()) for variable in self.joint_vars]
        try:
            self.controller.move_joints(angles, duration=0.0)
        except Exception as error:
            self.status_var.set(f"관절 이동 오류: {error}")

    def _set_joint_text(self, index: int, degree: float) -> None:
        self.joint_value_vars[index].set(
            f"{degree:6.1f}° · {angle_to_dxl(math.radians(degree))}"
        )

    def _set_joint_display(self, angles: list[float]) -> None:
        self._updating_joint_ui = True
        try:
            for index, angle in enumerate(angles):
                degree = math.degrees(angle)
                self.joint_vars[index].set(degree)
                self._set_joint_text(index, degree)
        finally:
            self._updating_joint_ui = False

    def _go_home(self) -> None:
        if not self._connected or self._moving:
            return
        self._moving = True
        self._set_joint_controls(False)
        self.status_var.set("홈 이동 중...")
        threading.Thread(target=self._home_worker, daemon=True).start()

    def _home_worker(self) -> None:
        error = None
        try:
            self.controller.home()
        except Exception as exc:
            error = exc
        self.after(0, self._home_finished, error)

    def _home_finished(self, error: Exception | None) -> None:
        self._moving = False
        if error is None:
            self._set_joint_display(HOME_ANGLES)
            self.status_var.set("홈 이동 완료")
        else:
            messagebox.showerror("홈 이동 오류", str(error), parent=self)
        self._set_joint_controls(self._connected)

    def _save_teaching_point(self) -> None:
        with self._lock:
            target = self._locked_target
        if not self._connected or target is None:
            return
        try:
            state = self.controller.read_joint_state(strict=True)
            cx, cy, _confidence, width, height = target
            self.dataset.add_point(
                (cx, cy),
                state.angles,
                (width, height),
                positions=state.positions,
            )
            self.dataset.save(self.teaching_path)
        except Exception as error:
            messagebox.showerror("교시점 저장 오류", str(error), parent=self)
            return
        self._set_joint_display(state.angles)
        with self._lock:
            self._locked_target = None
        self.lock_target_button.configure(text="1. Mouse 위치 고정")
        self._update_count()
        self.status_var.set(
            f"교시점 저장: pixel=({cx:.0f}, {cy:.0f}), "
            + ", ".join(
                f"J{i}={math.degrees(angle):.1f}°/{position}"
                for i, (angle, position) in enumerate(
                    zip(state.angles, state.positions), start=1
                )
            )
        )
        if self.on_changed is not None:
            self.on_changed()
        self._update_target_buttons(self._target is not None)

    def _remove_last_point(self) -> None:
        self.dataset.remove_last_point()
        if self.dataset.point_count:
            self.dataset.save(self.teaching_path)
        elif self.teaching_path.exists():
            self.teaching_path.unlink()
        self._update_count()
        if self.on_changed is not None:
            self.on_changed()

    def _update_count(self) -> None:
        ready = "자동 이동 가능" if self.dataset.is_ready else "추가 교시 필요"
        self.count_var.set(
            f"교시점 {self.dataset.point_count}개 / 최소 {MIN_TEACHING_POINTS}개 · {ready}"
        )

    def _update_target_buttons(self, mouse_detected: bool) -> None:
        interactive = self._connected and not self._moving
        lock_enabled = interactive and (
            mouse_detected or self._locked_target is not None
        )
        self.lock_target_button.configure(
            state="normal" if lock_enabled else "disabled"
        )
        save_enabled = interactive and self._locked_target is not None
        self.save_button.configure(state="normal" if save_enabled else "disabled")

    def close(self) -> None:
        if self._moving:
            messagebox.showinfo("로봇 이동 중", "이동 완료 후 창을 닫아 주세요.")
            return
        self._stop_event.set()
        if self._camera_thread.is_alive():
            self._camera_thread.join(timeout=2.0)
        if self._connected:
            try:
                self.controller.disconnect()
            except Exception:
                pass
            self._connected = False
        self.destroy()
        if self.on_closed is not None:
            self.on_closed()
