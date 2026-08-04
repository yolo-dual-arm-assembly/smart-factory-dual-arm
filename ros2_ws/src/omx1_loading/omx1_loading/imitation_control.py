"""교시된 Mouse 픽셀→관절 자세 데이터로 OMX를 자동 이동한다."""
from __future__ import annotations

import math
import threading
from collections import deque
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from ultralytics import YOLO

from common.camera import open_camera
from common.omx_controller import OmxConfig, OmxController
from omx1_loading.teaching import OmxTeachingDataset


class OmxTaughtVisionRunner:
    """Mouse를 안정적으로 탐지한 뒤 교시 관절 자세까지 한 번 이동한다."""

    def __init__(
        self,
        model_path: str | Path,
        teaching: OmxTeachingDataset,
        config: Optional[OmxConfig] = None,
        camera_index: int = 0,
        confidence: float = 0.5,
        hit_frames: int = 5,
    ) -> None:
        if not teaching.is_ready:
            raise ValueError("자동 이동에는 유효한 교시점이 최소 4개 필요합니다.")
        self.model = YOLO(str(model_path))
        self.teaching = teaching
        self.controller = OmxController(config)
        self.camera_index = camera_index
        self.confidence = confidence
        self.hit_frames = hit_frames
        self._recent_pixels: deque[tuple[float, float]] = deque(maxlen=hit_frames)
        self._stop_event = threading.Event()
        self._home_event = threading.Event()
        self._holding = False
        self._target_rejected = False

        self._mouse_ids = [
            class_id for class_id, name in self.model.names.items() if name == "mouse"
        ]
        if not self._mouse_ids:
            raise ValueError("선택한 YOLO 모델에 mouse 클래스가 없습니다.")

    def request_stop(self) -> None:
        self._stop_event.set()

    def request_home(self) -> None:
        self._home_event.set()

    def run(self) -> None:
        capture = open_camera(self.camera_index)
        connected = False
        try:
            grabbed, frame = capture.read()
            if not grabbed:
                raise RuntimeError("Mouse 자동 이동 카메라 영상을 읽지 못했습니다.")
            frame_size = (frame.shape[1], frame.shape[0])
            if frame_size != self.teaching.frame_size:
                raise RuntimeError(
                    f"교시 해상도 {self.teaching.frame_size}와 "
                    f"현재 카메라 해상도 {frame_size}가 다릅니다. 다시 교시하세요."
                )

            self.controller.connect()
            connected = True
            self.controller.home()
            print(
                f"[Teaching Vision] 시작 · 교시점 {self.teaching.point_count}개 · "
                "Mouse 탐지 대기"
            )

            while not self._stop_event.is_set():
                if self._home_event.is_set():
                    self._home_event.clear()
                    self.controller.home()
                    self._holding = False
                    self._reset_detection()
                    print("[Teaching Vision] 홈 복귀 · 다음 Mouse 탐지 대기")

                grabbed, frame = capture.read()
                if not grabbed:
                    raise RuntimeError("카메라 프레임을 읽지 못했습니다.")
                annotated, target = self._detect(frame)
                self._draw_teaching_area(annotated)

                if target is None:
                    self._reset_detection()
                elif not self._holding:
                    cx, cy, confidence = target
                    self._recent_pixels.append((cx, cy))
                    if len(self._recent_pixels) >= self.hit_frames:
                        stable_pixel = (
                            float(np.median([point[0] for point in self._recent_pixels])),
                            float(np.median([point[1] for point in self._recent_pixels])),
                        )
                        self._draw_target(annotated, stable_pixel, confidence)
                        if not self._target_rejected:
                            self._move_to_taught_pose(stable_pixel)

                state = "HOLD" if self._holding else "WAIT"
                cv2.putText(
                    annotated,
                    f"Teaching: {state}  points={self.teaching.point_count}",
                    (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (0, 200, 255),
                    2,
                )
                cv2.imshow("OMX Mouse Teaching Control", annotated)
                key = cv2.waitKey(1) & 0xFF
                if key == ord("q"):
                    break
                if key == ord("r") and self._holding:
                    self.request_home()
        finally:
            capture.release()
            cv2.destroyAllWindows()
            if connected:
                try:
                    self.controller.home()
                finally:
                    self.controller.disconnect()

    def _detect(
        self, frame: np.ndarray
    ) -> tuple[np.ndarray, tuple[float, float, float] | None]:
        result = self.model(
            frame,
            conf=self.confidence,
            classes=self._mouse_ids,
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
                )
                best_confidence = confidence
        return result.plot(img=frame.copy()), target

    def _move_to_taught_pose(self, pixel: tuple[float, float]) -> None:
        try:
            angles = self.teaching.predict(pixel)
        except ValueError as error:
            print(f"[Teaching Vision] 이동 거부: {error} · pixel={pixel}")
            self._target_rejected = True
            return
        print(
            f"[Teaching Vision] Mouse pixel=({pixel[0]:.0f}, {pixel[1]:.0f}) → "
            + ", ".join(
                f"J{index}={math.degrees(angle):.1f}°"
                for index, angle in enumerate(angles, start=1)
            )
        )
        self.controller.move_joints_smooth(angles, duration=5.0)
        self._holding = True
        self._reset_detection()
        print("[Teaching Vision] 교시 자세 도착 · R: 홈/재탐지, Q: 종료")

    @staticmethod
    def _draw_target(
        frame: np.ndarray, pixel: tuple[float, float], confidence: float
    ) -> None:
        cx, cy = round(pixel[0]), round(pixel[1])
        cv2.circle(frame, (cx, cy), 7, (0, 255, 0), -1)
        cv2.putText(
            frame,
            f"taught target ({cx}, {cy}) conf={confidence:.2f}",
            (cx + 10, cy - 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 0),
            2,
        )

    def _draw_teaching_area(self, frame: np.ndarray) -> None:
        pixels = np.asarray(
            [point.pixel for point in self.teaching.points], dtype=np.int32
        )
        if len(pixels) >= 3:
            hull = cv2.convexHull(pixels)
            cv2.polylines(frame, [hull], True, (255, 180, 0), 2)
        for index, pixel in enumerate(pixels, start=1):
            center = (int(pixel[0]), int(pixel[1]))
            cv2.circle(frame, center, 5, (255, 180, 0), -1)
            cv2.putText(
                frame,
                str(index),
                (center[0] + 7, center[1] - 7),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (255, 180, 0),
                1,
            )

    def _reset_detection(self) -> None:
        self._recent_pixels.clear()
        self._target_rejected = False
