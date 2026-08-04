"""메인 YOLO GUI에서 사용하는 카메라-OMX 좌표 캘리브레이션 창."""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable

import cv2
from PIL import Image, ImageTk

from common.camera import open_camera
from omx1_loading.coordinate_transform import OmxCalibration, make_full_frame_calibration


CALIBRATION_PREVIEW_SIZE = (960, 540)
CALIBRATION_X_RANGE_CM = (10.0, 25.0)
CALIBRATION_Y_RANGE_CM = (-15.0, 15.0)


class OmxCalibrationWindow(tk.Toplevel):
    """화면 클릭점과 입력한 로봇 XY 좌표의 대응점을 수집한다."""

    def __init__(
        self,
        master: tk.Misc,
        camera_index: int,
        save_path: Path,
        on_saved: Callable[[], None] | None = None,
        on_closed: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(master)
        self.title("OMX 카메라 좌표 캘리브레이션")
        self.geometry("1040x720")
        self.minsize(760, 580)

        self.save_path = save_path
        self.on_saved = on_saved
        self.on_closed = on_closed
        self.calibration = OmxCalibration()
        self.capture = open_camera(camera_index)
        self._frame = None
        self._photo: ImageTk.PhotoImage | None = None
        self._display_scale = 1.0
        self._closed = False

        self.robot_x_var = tk.StringVar()
        self.robot_y_var = tk.StringVar()
        self.point_count_var = tk.StringVar(value="등록점: 0개 / 최소 4개")

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(15, self._poll_camera)

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self.preview = ttk.Label(
            self,
            text="카메라 준비 중...",
            anchor="center",
            relief="solid",
        )
        self.preview.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.preview.bind("<Button-1>", self._add_clicked_point)

        controls = ttk.LabelFrame(self, text="대응점 등록", padding=10)
        controls.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))
        controls.columnconfigure(6, weight=1)

        ttk.Label(controls, text="클릭할 점의 로봇 좌표").grid(row=0, column=0)
        ttk.Label(controls, text="X(cm)").grid(row=0, column=1, padx=(12, 4))
        ttk.Entry(controls, textvariable=self.robot_x_var, width=8).grid(
            row=0, column=2
        )
        ttk.Label(controls, text="Y(cm)").grid(row=0, column=3, padx=(12, 4))
        ttk.Entry(controls, textvariable=self.robot_y_var, width=8).grid(
            row=0, column=4
        )
        ttk.Label(controls, textvariable=self.point_count_var).grid(
            row=0, column=5, padx=16
        )

        ttk.Button(
            controls,
            text="전체 화면 자동 설정",
            command=self._use_full_frame_calibration,
        ).grid(row=0, column=7, padx=(4, 0))
        ttk.Button(controls, text="마지막 점 취소", command=self._undo_point).grid(
            row=0, column=8, padx=(8, 0)
        )
        self.save_button = ttk.Button(
            controls,
            text="계산 및 저장",
            command=self._compute_and_save,
            state="disabled",
        )
        self.save_button.grid(row=0, column=9, padx=(8, 0))

        ttk.Label(
            controls,
            text=(
                "X/Y를 입력하고 영상의 해당 지점을 클릭하세요. "
                "로봇 기준 X=10~25cm, Y=-15~15cm이며 9점을 권장합니다."
            ),
            foreground="#555555",
        ).grid(row=1, column=0, columnspan=10, sticky="w", pady=(8, 0))

    def _poll_camera(self) -> None:
        if self._closed:
            return
        grabbed, frame = self.capture.read()
        if not grabbed:
            messagebox.showerror("카메라 오류", "캘리브레이션 영상을 읽지 못했습니다.")
            self.close()
            return

        self._frame = frame
        annotated = frame.copy()
        for index, point in enumerate(self.calibration.pixel_points, start=1):
            px, py = round(point[0]), round(point[1])
            cv2.circle(annotated, (px, py), 8, (0, 255, 0), -1)
            cv2.putText(
                annotated,
                str(index),
                (px + 10, py),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 0),
                2,
            )

        height, width = annotated.shape[:2]
        self._display_scale = min(
            CALIBRATION_PREVIEW_SIZE[0] / width,
            CALIBRATION_PREVIEW_SIZE[1] / height,
            1.0,
        )
        if self._display_scale < 1.0:
            annotated = cv2.resize(
                annotated,
                (round(width * self._display_scale), round(height * self._display_scale)),
                interpolation=cv2.INTER_AREA,
            )
        image = Image.fromarray(cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB))
        self._photo = ImageTk.PhotoImage(image)
        self.preview.configure(image=self._photo, text="")
        self.after(15, self._poll_camera)

    def _add_clicked_point(self, event: tk.Event) -> None:
        if self._frame is None:
            return
        try:
            robot_x_cm = float(self.robot_x_var.get())
            robot_y_cm = float(self.robot_y_var.get())
        except ValueError:
            messagebox.showwarning(
                "좌표 입력 필요", "먼저 로봇 X/Y 좌표를 cm 단위로 입력하세요."
            )
            return
        if not (
            CALIBRATION_X_RANGE_CM[0]
            <= robot_x_cm
            <= CALIBRATION_X_RANGE_CM[1]
            and CALIBRATION_Y_RANGE_CM[0]
            <= robot_y_cm
            <= CALIBRATION_Y_RANGE_CM[1]
        ):
            messagebox.showerror(
                "로봇 좌표 범위 오류",
                "입력값은 픽셀값이 아니라 로봇 베이스 기준 cm 좌표입니다.\n\n"
                "X: 정면 방향 10~25 cm\n"
                "Y: 왼쪽(+) / 오른쪽(-) -15~15 cm\n\n"
                f"현재 입력: X={robot_x_cm:g}, Y={robot_y_cm:g} cm",
                parent=self,
            )
            return
        robot_x = robot_x_cm / 100.0
        robot_y = robot_y_cm / 100.0

        if self._photo is None:
            return
        offset_x = max(0.0, (self.preview.winfo_width() - self._photo.width()) / 2)
        offset_y = max(0.0, (self.preview.winfo_height() - self._photo.height()) / 2)
        pixel_x = (event.x - offset_x) / self._display_scale
        pixel_y = (event.y - offset_y) / self._display_scale
        height, width = self._frame.shape[:2]
        if not (0 <= pixel_x < width and 0 <= pixel_y < height):
            return
        self.calibration.add_point((pixel_x, pixel_y), (robot_x, robot_y))
        self._update_point_status()

    def _undo_point(self) -> None:
        self.calibration.remove_last_point()
        self._update_point_status()

    def _use_full_frame_calibration(self) -> None:
        if self._frame is None:
            messagebox.showwarning("카메라 준비 중", "영상이 나타난 뒤 다시 눌러 주세요.")
            return
        confirmed = messagebox.askyesno(
            "전체 화면 자동 설정",
            "카메라 전체 화면을 다음 로봇 영역으로 설정합니다.\n\n"
            "화면 위쪽: X=23cm (먼 방향)\n"
            "화면 아래쪽: X=18cm (가까운 방향)\n"
            "화면 왼쪽: Y=+8cm\n"
            "화면 오른쪽: Y=-8cm\n\n"
            "카메라 방향이 이 설명과 맞습니까?",
            parent=self,
        )
        if not confirmed:
            return
        height, width = self._frame.shape[:2]
        self.calibration = make_full_frame_calibration(width, height)
        self._update_point_status()
        self._compute_and_save()

    def _update_point_status(self) -> None:
        count = self.calibration.point_count
        self.point_count_var.set(f"등록점: {count}개 / 최소 4개")
        self.save_button.configure(state="normal" if count >= 4 else "disabled")

    def _compute_and_save(self) -> None:
        try:
            self.calibration.compute()
            error_cm = self.calibration.reprojection_error() * 100.0
            self.calibration.save(self.save_path)
        except Exception as error:
            messagebox.showerror("캘리브레이션 오류", str(error), parent=self)
            return
        messagebox.showinfo(
            "캘리브레이션 완료",
            f"저장 완료: {self.save_path.name}\n평균 오차: {error_cm:.2f} cm",
            parent=self,
        )
        if self.on_saved is not None:
            self.on_saved()
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.capture.release()
        self.destroy()
        if self.on_closed is not None:
            self.on_closed()
