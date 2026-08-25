"""DetectionResult를 구독해 Homography 좌표변환 + OMX 제어로 픽 앤 플레이스를 실행하는 노드.

좌표계·집기 높이는 코드에 두지 않고 OmxCalibration이 로드하는 캘리브레이션
JSON(기본 경로: common.constants.OMX_CALIBRATION_PATH, 파라미터로 재정의 가능)에서
가져온다. 좌표 재설정은 그 JSON을 다시 만들면 되고 이 노드는 건드릴 필요 없다.

flag 처리 패턴 세 가지:
- 디바운싱: 연속 hit_frames 프레임 탐지됐을 때만 이동 시작 (오탐 1프레임에 반응 금지)
- 실패 유예: 연속 miss_frames 프레임 실패했을 때만 홈 복귀 (한 프레임 놓침에 중단 금지)
- 워치독: watchdog_sec 동안 메시지가 없으면 탐지 노드 다운으로 간주하고 정지

pick 시퀀스(APPROACH→DESCEND→GRAB→LIFT→PLACE→RELEASE→HOME)는 DYNAMIXEL SDK를
직접 블로킹 호출하므로 콜백 실행 중에는 워치독 타이머도 함께 멎는다. 단일 스레드
executor 기준으로는 의도된 동작이며, 시퀀스 도중 들어온 탐지 메시지는 busy 플래그로
무시한다.
"""
from __future__ import annotations

import time
from pathlib import Path

import rclpy
from rclpy.node import Node

from project_interfaces.msg import DetectionResult

from common.constants import OMX_CALIBRATION_PATH
from common.omx_controller import OmxConfig, OmxController
from omx1_loading.coordinate_transform import OmxCalibration
from omx1_loading.pick_ball import is_safe_approach_target
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


class ArmControllerNode(Node):
    def __init__(self) -> None:
        super().__init__("omx1_loading")
        self.declare_parameter("min_confidence", 0.6)
        self.declare_parameter("hit_frames", 3)
        self.declare_parameter("miss_frames", 5)
        self.declare_parameter("watchdog_sec", 1.0)
        self.declare_parameter("calibration_path", str(OMX_CALIBRATION_PATH))
        self.declare_parameter("omx_port", "")

        self.min_confidence = float(self.get_parameter("min_confidence").value)
        self.hit_frames = int(self.get_parameter("hit_frames").value)
        self.miss_frames = int(self.get_parameter("miss_frames").value)
        self.watchdog_sec = float(self.get_parameter("watchdog_sec").value)

        calibration_path = Path(str(self.get_parameter("calibration_path").value))
        if not calibration_path.exists():
            raise RuntimeError(
                f"캘리브레이션 파일 없음: {calibration_path}\n"
                "먼저 생성하세요: "
                "python -m omx1_loading.run_vision_pick --calibrate"
            )
        self.calibration = OmxCalibration.load(calibration_path)

        port = str(self.get_parameter("omx_port").value)
        config = OmxConfig(port=port) if port else OmxConfig()
        config.profile_velocity = PICK_PLACE_PROFILE_VELOCITY
        self.controller = OmxController(config)
        self.controller.connect()
        self.controller.home()

        self.hit_count = 0
        self.miss_count = 0
        self.tracking = False
        self.busy = False
        self.stopped_by_watchdog = False
        self.last_msg_time = None

        self.subscription = self.create_subscription(
            DetectionResult, "/yolo/detection", self.on_detection, 10
        )
        self.watchdog_timer = self.create_timer(0.2, self.check_watchdog)

    def on_detection(self, msg: DetectionResult) -> None:
        self.last_msg_time = self.get_clock().now()
        if self.stopped_by_watchdog:
            self.stopped_by_watchdog = False
            self.get_logger().info("탐지 노드 복구됨 — 제어 재개")

        if self.busy:
            return

        if msg.detected and msg.confidence >= self.min_confidence:
            self.hit_count += 1
            self.miss_count = 0
            if not self.tracking and self.hit_count >= self.hit_frames:
                self.tracking = True
                self.command_move(msg)
        else:
            self.miss_count += 1
            self.hit_count = 0
            if self.tracking and self.miss_count >= self.miss_frames:
                self.tracking = False
                self.command_home()

    def check_watchdog(self) -> None:
        if self.last_msg_time is None or self.stopped_by_watchdog:
            return
        elapsed = (self.get_clock().now() - self.last_msg_time).nanoseconds / 1e9
        if elapsed > self.watchdog_sec:
            self.stopped_by_watchdog = True
            self.tracking = False
            self.hit_count = 0
            self.miss_count = 0
            self.command_stop()

    # --- 실제 로봇팔 인터페이스 ---

    def command_move(self, msg: DetectionResult) -> None:
        cal = self.calibration
        rx, ry, _ = cal.pixel_to_robot(msg.cx, msg.cy)
        ry += Y_OFFSET_CORRECTION_M
        # 이동·접근 구간은 바구니/다른 공을 치지 않도록 캘리브레이션 높이보다 더 든다.
        travel_z = cal.approach_z + APPROACH_Z_MARGIN
        approach_target = (rx, ry, travel_z)
        if not is_safe_approach_target(*approach_target):
            self.get_logger().warning(f"안전 영역 밖 목표 거부 — XYZ={approach_target}")
            self.tracking = False
            self.hit_count = 0
            return

        self.get_logger().info(
            f"MOVE → 로봇좌표=({rx:.3f}, {ry:.3f}) "
            f"{msg.class_name} conf={msg.confidence:.2f}"
        )
        self.busy = True
        try:
            time.sleep(PRE_MOVE_WAIT_SEC)  # 탐지 확정 직후 바로 움직이지 않고 대기
            self.controller.config.profile_velocity = PICK_PLACE_PROFILE_VELOCITY
            self.controller.move_xyz(rx, ry, travel_z, duration=2.0)
            time.sleep(SETTLE_WAIT_SEC)  # pick 하강 직전, 흔들림이 멈추길 대기

            gripper_open_and_wait(self.controller)
            self.controller.config.profile_velocity = PICK_DESCEND_PROFILE_VELOCITY
            pick_target_z = cal.pick_z + PICK_Z_MARGIN
            self.controller.move_xyz(rx, ry, pick_target_z, duration=PICK_DESCEND_DURATION)
            gripper_close_and_wait(self.controller)

            self.controller.config.profile_velocity = PICK_PLACE_PROFILE_VELOCITY
            self.controller.move_xyz(rx, ry, travel_z, duration=1.7)
            px, py = cal.place_pos
            self.controller.move_xyz(px, py, travel_z, duration=2.3)
            time.sleep(SETTLE_WAIT_SEC)  # place 하강 직전, 흔들림이 멈추길 대기

            self.controller.config.profile_velocity = PLACE_DESCEND_PROFILE_VELOCITY
            place_target_z = cal.place_z + PLACE_Z_MARGIN
            self.controller.move_xyz(px, py, place_target_z, duration=PLACE_DESCEND_DURATION)

            gripper_release_and_wait(self.controller)

            # 바구니 바닥 근처(숙인 자세)에서 바로 home()으로 보간하면 팔이
            # 스스로에 걸린다 — 안전 높이로 먼저 들어올린다. 여기서 끝내고
            # home()은 부르지 않는다: 공이 아직 있으면 watchdog이 끊기기 전에
            # 다음 탐지가 바로 여기서(이미 든 상태로) 재시도하고, 진짜 없으면
            # watchdog(check_watchdog→command_stop)이 알아서 home으로 보낸다.
            self.controller.config.profile_velocity = PICK_PLACE_PROFILE_VELOCITY
            self.controller.move_xyz(px, py, travel_z, duration=2.0)
        finally:
            self.busy = False
            self.tracking = False
            self.hit_count = 0

    def command_home(self) -> None:
        self.get_logger().info("HOME — 탐지 끊김, 대기 자세로 복귀")
        self.controller.home()

    def command_stop(self) -> None:
        self.get_logger().warning(
            f"STOP — {self.watchdog_sec}s 동안 탐지 메시지 없음 (탐지 노드 다운 의심)"
        )
        self.controller.home()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = ArmControllerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            node.controller.home()
        finally:
            node.controller.disconnect()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
