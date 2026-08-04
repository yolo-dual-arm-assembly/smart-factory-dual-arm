"""웹캠 실시간 YOLO 탐지 창.

영상 프레임레이트가 추론 속도에 묶이지 않도록 스레드를 둘로 나눈다.

- 캡처 스레드: 카메라 프레임을 30fps로 읽어 마지막 추론 결과(박스/마스크)를
  현재 프레임 위에 합성해 표시용 프레임을 만든다.
- 추론 스레드: 최신 원본 프레임만 골라 YOLO 추론을 돌리고 결과를 남긴다.

영상은 항상 부드럽게 흐르고, 탐지 박스만 추론 속도(CPU 기준 ~10fps)로
갱신된다. Tk 위젯 갱신은 메인 스레드의 after 폴링 루프가 담당한다
(Tk는 스레드 안전하지 않다).
"""
from __future__ import annotations

import threading
import time
import tkinter as tk
import traceback
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable

import cv2
from PIL import Image, ImageTk
from ultralytics import YOLO

from common.camera import (
    _linux_camera_indexes,
    open_camera,
    open_preferred_camera,
    preferred_camera_indexes,
)
from system_monitor.ui.ui_fonts import configure_korean_fonts

WEBCAM_CONFIDENCE = 0.5
# 캡처(30fps)와 폴링이 어긋나며 프레임을 흘리지 않도록 캡처 주기의 절반으로 돈다.
VIEW_POLL_MS = 15
PREVIEW_MAX_SIZE = (960, 540)

SnapshotCallback = Callable[[Path], None]


class WebcamWindow(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        model_path: Path,
        input_dir: Path,
        on_snapshot: SnapshotCallback | None = None,
        camera_index: int | None = None,
    ) -> None:
        super().__init__(master)
        self.ui_font_family, _ = configure_korean_fonts(self)
        self.title(f"웹캠 실시간 탐지 — {model_path.name}")
        self.geometry("1000x640")
        self.minsize(640, 420)

        self.model_path = model_path
        self.input_dir = input_dir
        self.on_snapshot = on_snapshot
        self.camera_index = camera_index

        # 두 워커 스레드와 공유하는 상태 — 반드시 _lock 안에서만 접근한다.
        self._lock = threading.Lock()
        self._latest: tuple | None = None  # (preview_bgr, count, video_fps, infer_fps)
        self._raw_frame = None  # 추론/스냅샷용 최신 원본 (BGR)
        self._raw_seq = 0
        self._last_result = None
        self._infer_fps = 0.0
        self._error: str | None = None

        self._photo: ImageTk.PhotoImage | None = None
        self._snapshot_seq = 0
        self.frame_count = 0
        self.last_detected = False
        self._stop_event = threading.Event()

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.close)

        self._threads = [
            threading.Thread(target=self._capture_worker, daemon=True),
            threading.Thread(target=self._inference_worker, daemon=True),
        ]
        for thread in self._threads:
            thread.start()
        self.after(VIEW_POLL_MS, self._poll_frame)

    # ------------------------------------------------------------------ UI 구성

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self.video_label = ttk.Label(
            self,
            text="카메라 준비 중...",
            anchor="center",
            relief="solid",
        )
        self.video_label.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

        bottom = ttk.Frame(self, padding=(10, 0, 10, 10))
        bottom.grid(row=1, column=0, sticky="ew")
        bottom.columnconfigure(0, weight=1)

        self.flag_var = tk.StringVar(value="대기 중")
        self.flag_label = ttk.Label(
            bottom,
            textvariable=self.flag_var,
            font=(self.ui_font_family, 12, "bold"),
        )
        self.flag_label.grid(row=0, column=0, sticky="w")

        self.snapshot_button = ttk.Button(
            bottom, text="스냅샷 → 이미지 목록에 추가", command=self.save_snapshot
        )
        self.snapshot_button.grid(row=0, column=1, padx=(8, 0))

        ttk.Button(bottom, text="닫기", command=self.close).grid(
            row=0, column=2, padx=(8, 0)
        )

    # ------------------------------------------------------------------ 워커 스레드

    def _capture_worker(self) -> None:
        """카메라 속도(~30fps)로 프레임을 읽고 마지막 탐지 결과를 합성한다."""
        capture = None
        try:
            if self.camera_index is None:
                capture, camera_index = open_preferred_camera()
            else:
                capture = open_camera(self.camera_index)
                camera_index = self.camera_index
            print(f"[webcam] 카메라 {camera_index}번 사용")

            fps = 0.0
            last_time = time.perf_counter()
            while not self._stop_event.is_set():
                grabbed, frame = capture.read()
                if not grabbed:
                    raise RuntimeError("웹캠 프레임을 읽지 못했습니다.")
                now = time.perf_counter()
                elapsed, last_time = now - last_time, now
                if elapsed > 0:
                    fps = 0.9 * fps + 0.1 / elapsed if fps else 1.0 / elapsed

                with self._lock:
                    self._raw_frame = frame
                    self._raw_seq += 1
                    result = self._last_result
                    infer_fps = self._infer_fps

                if result is not None:
                    # plot은 전달한 이미지에 직접 그리므로 원본은 복사해 보호한다.
                    annotated = result.plot(img=frame.copy())
                    count = 0 if result.boxes is None else len(result.boxes)
                else:
                    annotated = frame
                    count = 0
                preview = self._scale_for_preview(annotated)

                with self._lock:
                    self._latest = (preview, count, fps, infer_fps)
        except Exception as error:
            traceback.print_exc()
            with self._lock:
                self._error = str(error)
        finally:
            if capture is not None:
                capture.release()

    def _inference_worker(self) -> None:
        """새 프레임이 있을 때만 추론하고 결과를 남긴다(밀린 프레임은 건너뛴다)."""
        try:
            model = YOLO(str(self.model_path))
            processed_seq = 0
            while not self._stop_event.is_set():
                with self._lock:
                    frame = self._raw_frame
                    seq = self._raw_seq
                if frame is None or seq == processed_seq:
                    time.sleep(0.005)
                    continue
                processed_seq = seq

                started = time.perf_counter()
                result = model(frame, conf=WEBCAM_CONFIDENCE, verbose=False)[0]
                elapsed = time.perf_counter() - started

                with self._lock:
                    self._last_result = result
                    self._infer_fps = (
                        0.9 * self._infer_fps + 0.1 / elapsed
                        if self._infer_fps
                        else 1.0 / elapsed
                    )
        except Exception as error:
            traceback.print_exc()
            with self._lock:
                self._error = str(error)

    @staticmethod
    def _scale_for_preview(frame):
        height, width = frame.shape[:2]
        scale = min(PREVIEW_MAX_SIZE[0] / width, PREVIEW_MAX_SIZE[1] / height, 1.0)
        if scale >= 1.0:
            return frame
        return cv2.resize(
            frame,
            (int(width * scale), int(height * scale)),
            interpolation=cv2.INTER_AREA,
        )

    # ------------------------------------------------------------------ 화면 갱신

    def _poll_frame(self) -> None:
        if not self.winfo_exists():
            return
        with self._lock:
            payload, self._latest = self._latest, None
            error, self._error = self._error, None

        if error is not None:
            messagebox.showerror("웹캠 오류", error, parent=self)
            self.close()
            return

        if payload is not None:
            preview, count, video_fps, infer_fps = payload
            image = Image.fromarray(cv2.cvtColor(preview, cv2.COLOR_BGR2RGB))
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

            detected = count > 0
            self.last_detected = detected
            self.frame_count += 1
            flag_text = "DETECTED" if detected else "NO DETECT"
            self.flag_var.set(
                f"{flag_text} · {count}개 · 영상 {video_fps:.1f} FPS"
                f" · 추론 {infer_fps:.1f} FPS"
            )
            self.flag_label.configure(foreground="green" if detected else "red")

        self.after(VIEW_POLL_MS, self._poll_frame)

    # ------------------------------------------------------------------ 스냅샷/종료

    def save_snapshot(self) -> Path | None:
        """탐지 박스 없는 원본 프레임을 입력 폴더에 저장해 분석 대상으로 만든다."""
        with self._lock:
            raw = self._raw_frame
        if raw is None:
            messagebox.showwarning(
                "스냅샷", "아직 저장할 프레임이 없습니다.", parent=self
            )
            return None
        self._snapshot_seq += 1
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        snapshot_path = (
            self.input_dir / f"webcam_{timestamp}_{self._snapshot_seq}.jpg"
        )
        cv2.imwrite(str(snapshot_path), raw)
        print(f"[webcam snapshot] {snapshot_path.name} → 이미지 목록에 추가")
        if self.on_snapshot is not None:
            self.on_snapshot(snapshot_path)
        return snapshot_path

    def close(self) -> None:
        if not self.winfo_exists():
            return
        self._stop_event.set()
        for thread in self._threads:
            if thread.is_alive():
                thread.join(timeout=2.0)
        self.destroy()
