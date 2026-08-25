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
from common.camera import open_camera
from common.omx_controller import (
    OMX_BASE_X,
    OMX_L0,
    OMX_L1,
    OMX_L2,
    OMX_L3,
    OMX_TOOL_PITCH,
    OmxController,
    OmxConfig,
    ik_5dof,
)
from omx1_loading.pick_place_tuning import (
    APPROACH_Z_MARGIN,
    PICK_DESCEND_DURATION,
    PICK_DESCEND_PROFILE_VELOCITY,
    PICK_PLACE_PROFILE_VELOCITY,
    PICK_Z_MARGIN,
    PLACE_DESCEND_DURATION,
    PLACE_DESCEND_PROFILE_VELOCITY,
    PLACE_Z_MARGIN,
    PRE_MOVE_WAIT_SEC,
    SETTLE_WAIT_SEC,
    Y_OFFSET_CORRECTION_M,
    gripper_close_and_wait,
    gripper_open_and_wait,
    gripper_release_and_wait,
)


# 허용 작업 영역(로봇 베이스 기준, m). 로봇·카메라를 옮기고 다시 캘리브레이션한
# 9점의 실측 범위(X -16.2~2.4cm, Y -27.7~-13.3cm)에 여유 2cm를 더했다.
# 로봇을 또 옮기면 이 범위도 다시 맞춰야 한다.
SAFE_X_RANGE = (-0.18, 0.04)
SAFE_Y_RANGE = (-0.30, -0.11)

_MAX_REACH = OMX_L1 + OMX_L2


def max_horizontal_reach(z: float) -> float:
    """그리퍼가 수직 아래를 향한 채, 높이 z(m)에서 닿을 수 있는 최대 수평
    반경(m)을 반환한다. 높이가 올라갈수록 줄어든다(``ik_5dof``와 같은 기하).
    """
    wrist_z = z + OMX_L3 * math.sin(OMX_TOOL_PITCH) - OMX_L0
    remaining = _MAX_REACH ** 2 - wrist_z ** 2
    return math.sqrt(remaining) if remaining > 0 else 0.0


def is_in_safe_rectangle(x: float, y: float) -> bool:
    """목표점이 지정 작업 사각형 안인지 확인한다."""
    return (
        SAFE_X_RANGE[0] <= x <= SAFE_X_RANGE[1]
        and SAFE_Y_RANGE[0] <= y <= SAFE_Y_RANGE[1]
    )


def is_reachable(x: float, y: float, z: float) -> bool:
    """역기구학 해가 존재하고 관절 한계 안인지 확인한다."""
    try:
        ik_5dof(x, y, z)
    except ValueError:
        return False
    return True


def is_safe_approach_target(x: float, y: float, z: float) -> bool:
    """목표점이 지정 작업 영역과 역기구학 범위 안에 있는지 확인한다."""
    return is_in_safe_rectangle(x, y) and is_reachable(x, y, z)


def validate_calibration_workspace(calibration: OmxCalibration) -> None:
    """캘리브레이션 좌표의 단위와 OMX 작업 영역을 확인한다.

    작업 사각형은 팔이 실제로 그리는 영역보다 넓다. 사각형의 네 모서리는
    역기구학으로 도달하지 못하므로 사각형 검사만으로는 부족하고, 실제로 쓸
    두 높이(접근·집기)에서 해가 나오는지까지 확인한다.

    여기서 걸리는 점이 있어도 실행을 막지는 않는다 — 실제 pick 루프의
    ``is_safe_approach_target``이 매 프레임 다시 확인해서 도달 불가능한
    목표는 그 프레임만 건너뛰므로, 캘리브레이션 점 일부가 애매해도 나머지
    점으로는 정상 동작한다. 경고만 찍어서 어떤 점이 의심스러운지 알려준다.
    """
    outside_rectangle = [
        (x, y) for x, y in calibration.robot_points if not is_in_safe_rectangle(x, y)
    ]
    if outside_rectangle:
        formatted = ", ".join(
            f"({x * 100:.1f}, {y * 100:.1f})cm" for x, y in outside_rectangle
        )
        print(
            "[Calibration] 경고 — 작업 영역 밖 좌표 포함: "
            f"{formatted}. X={SAFE_X_RANGE[0] * 100:.0f}~{SAFE_X_RANGE[1] * 100:.0f}cm, "
            f"Y={SAFE_Y_RANGE[0] * 100:.0f}~{SAFE_Y_RANGE[1] * 100:.0f}cm 범위 밖."
        )

    work_heights = (calibration.approach_z, calibration.pick_z)
    unreachable = [
        (x, y, blocked)
        for x, y in calibration.robot_points
        if (blocked := [z for z in work_heights if not is_reachable(x, y, z)])
    ]
    if unreachable:
        formatted = ", ".join(
            f"({x * 100:.1f}, {y * 100:.1f})cm"
            f"[Z={'/'.join(f'{z * 100:.1f}' for z in heights)}cm]"
            for x, y, heights in unreachable
        )
        print(
            "[Calibration] 경고 — 역기구학 도달 범위 밖 좌표 포함: "
            f"{formatted}. 이 근처 공은 pick 시도 시 '안전 영역 밖 목표 거부'로 "
            "건너뛴다."
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
        # State.WAIT는 "진짜 홈"과 "픽업 끝나고 travel_z에서 대기 중" 둘 다에
        # 쓰여서, 홈 복귀 여부는 이 플래그로 따로 추적한다 — 안 그러면 픽업 후
        # 공이 더 없어도 다시 홈으로 안 간다.
        self._at_home = True

        validate_calibration_workspace(self.calibration)
        self._safe_zone_pixels = self._compute_safe_zone_pixels()
        self._reach_circle_pixels = self._compute_reach_circle_pixels()

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
        # click_calibration_points.py/measure_calibration_points.py/vision_node와
        # 같은 해상도(기본 1280x720)로 열어야 한다 — 다르면 픽셀 좌표 스케일이
        # 어긋나 캘리브레이션(Homography)이 전부 틀어진다.
        cap = open_camera(self.camera_index)
        actual_w = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
        actual_h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        print(f"[Vision] 카메라 실제 해상도: {actual_w:.0f}x{actual_h:.0f}")
        if (actual_w, actual_h) != (1280, 720):
            print(
                "[Vision] 경고 — 캘리브레이션은 1280x720 기준인데 실제 캡처가 "
                "다릅니다. 좌표가 어긋날 수 있습니다."
            )

        connected = False
        try:
            self.controller.connect()
            connected = True
            self.controller.home()
            self._at_home = True
            print(f"[Vision] 시작 — 모델: {self.model.model_name}, "
                  f"클래스: {self.target_class or '전체'}")

            while not self._stop_event.is_set():
                if self._home_event.is_set():
                    self._home_event.clear()
                    print("[Vision] GUI 요청 — 홈 복귀 후 다시 탐지")
                    self.controller.home()
                    self._at_home = True
                    self._state = State.WAIT
                    self._last_target = None
                    self._reset_detection()

                ret, frame = cap.read()
                if not ret:
                    break

                result_frame, detected, cx, cy, conf = self._detect(frame)
                self._draw_safe_zone(result_frame)
                self._draw_reach_circle(result_frame)

                is_hit = detected and conf >= self.confidence
                if is_hit:
                    self._recent_pixels.append((cx, cy))
                    stable_cx = float(np.median([p[0] for p in self._recent_pixels]))
                    stable_cy = float(np.median([p[1] for p in self._recent_pixels]))
                    rx, ry, rz = self.calibration.pixel_to_robot(stable_cx, stable_cy)
                    ry += Y_OFFSET_CORRECTION_M
                    robot_xyz = (rx, ry, rz)
                    # 이동·접근 구간은 바구니/다른 공을 치지 않도록
                    # 캘리브레이션 높이보다 더 든다 (loading_node.py와 동일).
                    travel_z = self.calibration.approach_z + APPROACH_Z_MARGIN
                    approach_target = (rx, ry, travel_z)

                    if not is_safe_approach_target(*approach_target):
                        # 안전 영역 밖 — 요청대로 탐지 자체를 무시한다
                        # (아래 미탐지 처리에서 _reset_detection()이 정리한다).
                        is_hit = False
                    else:
                        self._hit_count += 1
                        self._miss_count = 0
                        self._last_target = robot_xyz
                        self._draw_info(
                            result_frame, stable_cx, stable_cy, robot_xyz, conf
                        )

                        if (
                            self._state == State.WAIT
                            and self._hit_count >= self.hit_frames
                        ):
                            print(f"[Vision] mouse 탐지 확정 — XYZ={approach_target}")
                            time.sleep(PRE_MOVE_WAIT_SEC)
                            self._execute_action(robot_xyz)

                if not is_hit:
                    self._reset_detection()
                    self._miss_count += 1
                    # 한 프레임 놓쳤다고 중단하지 않되, 연속으로 놓치면 팔을
                    # 뻗은 채로 방치하지 않고 홈으로 접는다. State.WAIT는 진짜
                    # 홈과 "픽업 직후 travel_z 대기"에 둘 다 쓰이므로 여기선
                    # _at_home으로 판단한다.
                    if (
                        not self._at_home
                        and self._miss_count >= self.miss_frames
                    ):
                        print(
                            f"[Vision] {self.miss_frames}프레임 연속 탐지 실패 — 홈 복귀"
                        )
                        self.controller.home()
                        self._at_home = True
                        self._state = State.WAIT
                        self._last_target = None
                        self._miss_count = 0

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
        """YOLO 추론을 수행하고 최고 신뢰도 탐지 결과를 반환한다.

        ``results[0].plot()``으로 자동 주석을 달지 않는다 — 그러면 안전영역
        밖 탐지도 무조건 박스가 그려져서, 안전영역 밖은 탐지 자체를 무시하는
        정책과 어긋난다. 화면 표시는 호출자가 안전 여부를 확인한 뒤
        ``_draw_info``로 직접 그린다.
        """
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

        return frame.copy(), found, best_cx, best_cy, best_conf

    def _execute_action(self, robot_xyz: tuple[float, float, float]) -> None:
        """탐지 위치에 따른 로봇 동작을 실행한다 (max_stage까지).

        속도·높이·그리퍼 값은 ``loading_node.py``(ROS 노드)와 동일하게
        ``pick_place_tuning``을 공유한다 — 여기서만 고치면 ROS 쪽과
        동작이 어긋난다.
        """
        rx, ry, rz = robot_xyz
        cal = self.calibration
        travel_z = cal.approach_z + APPROACH_Z_MARGIN

        # 1. APPROACH: 물체 위 접근 높이로 이동
        self._state = State.APPROACH
        self.controller.config.profile_velocity = PICK_PLACE_PROFILE_VELOCITY
        self.controller.move_xyz(rx, ry, travel_z, duration=2.0)
        cv2.waitKey(1)  # 긴 블로킹 시퀀스 중에도 창이 죽지 않게 이벤트를 처리
        if self.max_stage == State.APPROACH:
            print("[Vision] mouse 위 접근 완료 — R: 홈 복귀/재탐지, Q: 종료")
            self._reset_detection()
            return
        time.sleep(SETTLE_WAIT_SEC)  # pick 하강 직전, 흔들림이 멈추길 대기

        # 2. DESCEND: 집을 높이로 하강 (그리퍼는 미리 살짝만 열어둔다)
        self._state = State.DESCEND
        gripper_open_and_wait(self.controller)
        self.controller.config.profile_velocity = PICK_DESCEND_PROFILE_VELOCITY
        pick_target_z = cal.pick_z + PICK_Z_MARGIN
        self.controller.move_xyz(rx, ry, pick_target_z, duration=PICK_DESCEND_DURATION)
        cv2.waitKey(1)
        if self.max_stage == State.DESCEND:
            self.controller.home()
            self._at_home = True
            self._state = State.WAIT
            return

        # 3. GRAB: 그리퍼 닫기
        self._state = State.GRAB
        gripper_close_and_wait(self.controller)
        cv2.waitKey(1)

        # 4. LIFT: 들어올리기
        self._state = State.LIFT
        self.controller.config.profile_velocity = PICK_PLACE_PROFILE_VELOCITY
        self.controller.move_xyz(rx, ry, travel_z, duration=1.7)
        cv2.waitKey(1)

        # 5. PLACE: 내려놓을 위치로 이동 후 하강
        self._state = State.PLACE
        px, py = cal.place_pos
        self.controller.move_xyz(px, py, travel_z, duration=2.3)
        cv2.waitKey(1)
        time.sleep(SETTLE_WAIT_SEC)  # place 하강 직전, 흔들림이 멈추길 대기
        self.controller.config.profile_velocity = PLACE_DESCEND_PROFILE_VELOCITY
        place_target_z = cal.place_z + PLACE_Z_MARGIN
        self.controller.move_xyz(px, py, place_target_z, duration=PLACE_DESCEND_DURATION)
        cv2.waitKey(1)

        # 6. RELEASE: 그리퍼 조금만 열기 (완전 개방하면 옆 공을 건드림)
        self._state = State.RELEASE
        gripper_release_and_wait(self.controller)
        cv2.waitKey(1)

        # 7. 안전 높이로만 복귀 — 숙인 자세에서 바로 home()으로 보간하면
        # 팔이 스스로에 걸린다. 여기서 home()을 부르지 않는 이유는
        # run()의 WAIT 루프가 그대로 이어받기 때문이다: 공이 아직 있으면
        # 이 위치에서 바로 재시도하고, 없으면 miss_frames 연속 실패 시
        # run() 쪽 로직이 home()을 부른다. _at_home=False로 표시해둬야
        # 그 판단이 "이미 홈"으로 착각하지 않는다.
        self._state = State.HOME
        self.controller.config.profile_velocity = PICK_PLACE_PROFILE_VELOCITY
        self.controller.move_xyz(px, py, travel_z, duration=2.0)
        self._at_home = False
        self._state = State.WAIT
        self._hit_count = 0

    def _reset_detection(self) -> None:
        self._hit_count = 0
        self._recent_pixels.clear()

    def _compute_safe_zone_pixels(self) -> list[tuple[int, int]]:
        """SAFE_X_RANGE×SAFE_Y_RANGE 사각형의 네 꼭짓점을 픽셀 좌표로 변환한다.

        Homography는 원근 변환이라 로봇 좌표계의 직사각형이 화면에서는
        사다리꼴 등으로 보일 수 있다 — 그래도 4점을 이어 그리면 실제
        경계가 된다.
        """
        corners = [
            (SAFE_X_RANGE[0], SAFE_Y_RANGE[0]),
            (SAFE_X_RANGE[1], SAFE_Y_RANGE[0]),
            (SAFE_X_RANGE[1], SAFE_Y_RANGE[1]),
            (SAFE_X_RANGE[0], SAFE_Y_RANGE[1]),
        ]
        return [
            (int(u), int(v))
            for u, v in (self.calibration.robot_to_pixel(x, y) for x, y in corners)
        ]

    def _draw_safe_zone(self, frame: np.ndarray) -> None:
        """안전 작업 영역 경계를 화면에 겹쳐 그린다."""
        points = np.array(self._safe_zone_pixels, dtype=np.int32)
        cv2.polylines(frame, [points], isClosed=True, color=(0, 165, 255), thickness=2)
        cv2.putText(
            frame,
            "Safe zone",
            self._safe_zone_pixels[0],
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 165, 255), 2,
        )

    def _compute_reach_circle_pixels(self, n: int = 72) -> list[tuple[int, int]]:
        """이동 높이(travel_z)에서 실제 역기구학으로 닿는 최대 반경 원을
        픽셀 좌표로 변환한다. 그리퍼가 항상 수직 아래를 향한다는 이 로봇의
        가정 덕에, 닿는 범위는 베이스 중심(OMX_BASE_X, 0) 기준 원이 된다.
        """
        travel_z = self.calibration.approach_z + APPROACH_Z_MARGIN
        radius = max_horizontal_reach(travel_z)
        points: list[tuple[int, int]] = []
        for i in range(n):
            theta = 2 * math.pi * i / n
            x = OMX_BASE_X + radius * math.cos(theta)
            y = radius * math.sin(theta)
            u, v = self.calibration.robot_to_pixel(x, y)
            points.append((int(u), int(v)))
        return points

    def _draw_reach_circle(self, frame: np.ndarray) -> None:
        """역기구학으로 실제 도달 가능한 최대 범위 경계를 겹쳐 그린다."""
        if len(self._reach_circle_pixels) < 3:
            return
        points = np.array(self._reach_circle_pixels, dtype=np.int32)
        cv2.polylines(frame, [points], isClosed=True, color=(255, 200, 0), thickness=2)
        cv2.putText(
            frame,
            "Max reach",
            self._reach_circle_pixels[0],
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 200, 0), 2,
        )

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
