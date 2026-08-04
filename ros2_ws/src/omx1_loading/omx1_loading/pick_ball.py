"""YOLO 비전 인식 + OMX 로봇팔 제어 통합 실행 루프.

동작 흐름:
    WAIT       : 탐지 대기 (연속 N프레임 탐지 필요)
    APPROACH   : 목표 물체 위 접근 높이로 팔 이동
    DESCEND    : 집을 높이로 하강
    GRAB       : 그리퍼 닫기 (물체 집기)
    LIFT       : 들어올리기
    PLACE      : 내려놓을 위치로 이동
    RELEASE    : 그리퍼 열기 (놓기)
    HOME       : 홈 포즈로 복귀

초기 단계에서는 APPROACH까지만 동작하도록 단계를 제한할 수 있다.
"""
from __future__ import annotations

import math
import threading
import time
from collections import deque
from enum import Enum, auto
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from ultralytics import YOLO

from omx1_loading.coordinate_transform import OmxCalibration
from common.omx_controller import OmxController, OmxConfig, ik_5dof


# 첫 비전 연동 시험에서 허용할 보수적인 작업 영역(로봇 베이스 기준, m)
SAFE_X_RANGE = (0.10, 0.25)
SAFE_Y_RANGE = (-0.15, 0.15)


def is_safe_approach_target(x: float, y: float, z: float) -> bool:
    """목표점이 지정 작업 영역과 역기구학 범위 안에 있는지 확인한다."""
    if not (SAFE_X_RANGE[0] <= x <= SAFE_X_RANGE[1]):
        return False
    if not (SAFE_Y_RANGE[0] <= y <= SAFE_Y_RANGE[1]):
        return False
    try:
        ik_5dof(x, y, z)
    except ValueError:
        return False
    return True


def validate_calibration_workspace(calibration: OmxCalibration) -> None:
    """캘리브레이션 좌표의 단위와 OMX 작업 영역을 확인한다."""
    invalid_points = [
        (x, y)
        for x, y in calibration.robot_points
        if not (
            SAFE_X_RANGE[0] <= x <= SAFE_X_RANGE[1]
            and SAFE_Y_RANGE[0] <= y <= SAFE_Y_RANGE[1]
        )
    ]
    if invalid_points:
        formatted = ", ".join(
            f"({x * 100:.1f}, {y * 100:.1f})cm" for x, y in invalid_points
        )
        raise ValueError(
            "캘리브레이션 로봇 좌표가 작업 영역 밖입니다: "
            f"{formatted}. X=10~25cm, Y=-15~15cm로 다시 설정하세요."
        )


class State(Enum):
    WAIT    = auto()
    APPROACH = auto()
    DESCEND = auto()
    GRAB    = auto()
    LIFT    = auto()
    PLACE   = auto()
    RELEASE = auto()
    HOME    = auto()


class OmxVisionRunner:
    """실시간 웹캠 YOLO 탐지 + OMX 제어 통합 클래스.

    Args:
        model_path: YOLO 가중치 경로 (예: "best.pt")
        calibration: OmxCalibration 객체 (픽셀↔로봇 좌표 변환)
        config: OmxConfig 객체 (포트, Baudrate 등)
        target_class: 탐지할 클래스 이름 (None이면 모든 클래스)
        confidence: YOLO 신뢰도 임계값
        hit_frames: 이동 명령 전 연속 탐지 필요 프레임 수
        miss_frames: 홈 복귀 전 연속 실패 허용 프레임 수
        camera_index: 웹캠 인덱스
        max_stage: 최대 실행 단계 (State.APPROACH: 접근만, State.HOME: 전체)
    """

    def __init__(
        self,
        model_path: str | Path,
        calibration: OmxCalibration,
        config: Optional[OmxConfig] = None,
        target_class: Optional[str] = None,
        confidence: float = 0.5,
        hit_frames: int = 5,
        miss_frames: int = 5,
        camera_index: int = 0,
        max_stage: State = State.APPROACH,  # 초기값: 접근만 실행
    ) -> None:
        self.model = YOLO(str(model_path))
        self.calibration = calibration
        self.controller = OmxController(config)
        self.target_class = target_class
        self.confidence = confidence
        self.hit_frames = hit_frames
        self.miss_frames = miss_frames
        self.camera_index = camera_index
        self.max_stage = max_stage

        self._state = State.WAIT
        self._hit_count = 0
        self._miss_count = 0
        self._last_target: Optional[tuple[float, float, float]] = None
        self._recent_pixels: deque[tuple[float, float]] = deque(maxlen=hit_frames)
        self._stop_event = threading.Event()
        self._home_event = threading.Event()
        self._target_rejected = False

        validate_calibration_workspace(self.calibration)

        class_names = set(self.model.names.values())
        if self.target_class and self.target_class not in class_names:
            raise ValueError(
                f"모델에 '{self.target_class}' 클래스가 없습니다. "
                f"사용 가능 클래스: {sorted(class_names)}"
            )

    # --- 실행 ---

    def run(self) -> None:
        """웹캠에서 프레임을 읽어 YOLO 탐지 → OMX 제어를 반복한다.

        'q' 키를 누르면 종료한다.
        """
        cap = cv2.VideoCapture(self.camera_index)
        if not cap.isOpened():
            raise RuntimeError(f"카메라 {self.camera_index}번을 열 수 없습니다.")

        connected = False
        try:
            self.controller.connect()
            connected = True
            self.controller.home()
            print(f"[Vision] 시작 — 모델: {self.model.model_name}, "
                  f"클래스: {self.target_class or '전체'}")

            while not self._stop_event.is_set():
                if self._home_event.is_set():
                    self._home_event.clear()
                    print("[Vision] GUI 요청 — 홈 복귀 후 다시 탐지")
                    self.controller.home()
                    self._state = State.WAIT
                    self._last_target = None
                    self._reset_detection()

                ret, frame = cap.read()
                if not ret:
                    break

                result_frame, detected, cx, cy, conf = self._detect(frame)

                if detected and conf >= self.confidence:
                    self._hit_count += 1
                    self._miss_count = 0
                    self._recent_pixels.append((cx, cy))
                    stable_cx = float(np.median([p[0] for p in self._recent_pixels]))
                    stable_cy = float(np.median([p[1] for p in self._recent_pixels]))
                    robot_xyz = self.calibration.pixel_to_robot(stable_cx, stable_cy)
                    self._last_target = robot_xyz
                    self._draw_info(
                        result_frame, stable_cx, stable_cy, robot_xyz, conf
                    )

                    if (
                        self._state == State.WAIT
                        and not self._target_rejected
                        and self._hit_count >= self.hit_frames
                    ):
                        rx, ry, _ = robot_xyz
                        approach_target = (rx, ry, self.calibration.approach_z)
                        if is_safe_approach_target(*approach_target):
                            print(f"[Vision] mouse 탐지 확정 — XYZ={approach_target}")
                            self._execute_action(robot_xyz)
                        else:
                            print(
                                "[Vision] 안전 영역 밖 목표 거부 — "
                                f"XYZ={approach_target}"
                            )
                            self._reset_detection(reset_rejection=False)
                            self._target_rejected = True
                else:
                    self._reset_detection()
                    self._miss_count += 1

                cv2.imshow("OMX Vision Control", result_frame)
                key = cv2.waitKey(1)
                if key & 0xFF == ord("q"):
                    break
                if key & 0xFF == ord("r") and self._state != State.WAIT:
                    self.request_home()

        finally:
            cap.release()
            cv2.destroyAllWindows()
            if connected:
                try:
                    self.controller.home()
                finally:
                    self.controller.disconnect()

    def request_stop(self) -> None:
        """현재 동작을 마친 뒤 홈으로 복귀하고 실행 루프를 종료한다."""
        self._stop_event.set()

    def request_home(self) -> None:
        """비전 실행을 유지하면서 홈 복귀를 요청한다."""
        self._home_event.set()

    # --- 내부 메서드 ---

    def _detect(
        self, frame: np.ndarray
    ) -> tuple[np.ndarray, bool, float, float, float]:
        """YOLO 추론을 수행하고 최고 신뢰도 탐지 결과를 반환한다."""
        results = self.model(frame, verbose=False, conf=self.confidence)
        best_conf = 0.0
        best_cx = best_cy = 0.0
        found = False

        if results and results[0].boxes is not None:
            for box in results[0].boxes:
                cls_name = self.model.names[int(box.cls)]
                if self.target_class and cls_name != self.target_class:
                    continue
                c = float(box.conf)
                if c > best_conf:
                    best_conf = c
                    x1, y1, x2, y2 = box.xyxy[0]
                    best_cx = float((x1 + x2) / 2)
                    best_cy = float((y1 + y2) / 2)
                    found = True

        annotated = results[0].plot() if results else frame
        return annotated, found, best_cx, best_cy, best_conf

    def _execute_action(self, robot_xyz: tuple[float, float, float]) -> None:
        """탐지 위치에 따른 로봇 동작을 실행한다 (max_stage까지)."""
        rx, ry, rz = robot_xyz
        cal = self.calibration

        # 1. APPROACH: 물체 위 접근 높이로 이동
        self._state = State.APPROACH
        approach_angles = ik_5dof(rx, ry, cal.approach_z)
        print(
            "[Vision] OMX-F IK 목표 관절각 — "
            + ", ".join(
                f"J{index}={math.degrees(angle):.1f}°"
                for index, angle in enumerate(approach_angles, start=1)
            )
        )
        self.controller.move_joints_smooth(approach_angles, duration=5.0)
        if self.max_stage == State.APPROACH:
            print("[Vision] mouse 위 접근 완료 — R: 홈 복귀/재탐지, Q: 종료")
            self._reset_detection()
            return

        # 2. DESCEND: 집을 높이로 하강
        self._state = State.DESCEND
        self.controller.move_xyz(rx, ry, cal.pick_z, duration=1.0)
        if self.max_stage == State.DESCEND:
            time.sleep(1.0)
            self.controller.home()
            self._state = State.WAIT
            return

        # 3. GRAB: 그리퍼 닫기
        self._state = State.GRAB
        self.controller.gripper_close()

        # 4. LIFT: 들어올리기
        self._state = State.LIFT
        self.controller.move_xyz(rx, ry, cal.approach_z, duration=1.0)

        # 5. PLACE: 내려놓을 위치로 이동
        self._state = State.PLACE
        px, py = cal.place_pos
        self.controller.move_xyz(px, py, cal.approach_z, duration=1.5)
        self.controller.move_xyz(px, py, cal.place_z, duration=1.0)

        # 6. RELEASE: 그리퍼 열기
        self._state = State.RELEASE
        self.controller.gripper_open()

        # 7. HOME
        self._state = State.HOME
        self.controller.home(duration=2.0)
        self._state = State.WAIT
        self._hit_count = 0

    def _reset_detection(self, reset_rejection: bool = True) -> None:
        self._hit_count = 0
        self._recent_pixels.clear()
        if reset_rejection:
            self._target_rejected = False

    def _draw_info(
        self,
        frame: np.ndarray,
        cx: float,
        cy: float,
        robot_xyz: tuple[float, float, float],
        conf: float,
    ) -> None:
        """화면에 탐지 정보를 오버레이로 표시한다."""
        rx, ry, rz = robot_xyz
        cv2.circle(frame, (int(cx), int(cy)), 6, (0, 255, 0), -1)
        cv2.putText(
            frame,
            f"Robot: ({rx*100:.1f}cm, {ry*100:.1f}cm) conf={conf:.2f}",
            (int(cx) + 10, int(cy) - 10),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2,
        )
        cv2.putText(
            frame,
            f"State: {self._state.name}  hits={self._hit_count}",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 200, 255), 2,
        )
