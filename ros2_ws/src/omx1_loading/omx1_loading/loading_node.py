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
from common.omx_controller import OmxConfig, OmxController, gripper_percent_to_dxl
from omx1_loading.coordinate_transform import OmxCalibration
from omx1_loading.pick_ball import is_safe_approach_target

# 픽 앤 플레이스 속도/타이밍 — 탁구공을 놓치지 않도록 느리게 잡았다.
# 실기 모터가 Drive Mode(주소 10) bit2=1로 "Time-based Profile"이라
# Profile Velocity(config.profile_velocity)는 rpm이 아니라 목표까지
# 도달하는 데 걸리는 시간(ms)이다 — 값이 클수록 느리다(0=최대 속도).
PICK_PLACE_PROFILE_VELOCITY = 2500  # 수평 이동/접근 구간, 2.5초
DESCEND_PROFILE_VELOCITY = 5000  # pick·place 하강 구간, 5초로 더 느리게
DESCEND_DURATION = 6.0  # DESCEND_PROFILE_VELOCITY(5초)보다 넉넉하게 대기
SETTLE_WAIT_SEC = 1.0  # pick·place 하강 직전, 흔들림이 멈추길 기다리는 시간
# 그리퍼는 move_xyz와 별개로 자기 속도(ms)를 쓰므로 열고/닫기 직전에
# enable_torque()로 다시 눌러줘야 한다 — 안 그러면 직전 이동 속도가 남아있어
# 그리퍼 동작이 끝나기 전에 다음 동작이 시작돼버린다.
GRIPPER_PROFILE_VELOCITY = 1200  # 그리퍼 개폐 시간, 1.2초
GRIPPER_OPEN_DURATION = 1.8  # GRIPPER_PROFILE_VELOCITY보다 넉넉하게 대기
GRIPPER_CLOSE_DURATION = 1.8
# 바구니에서 그리퍼를 여는 정도. 0=완전 개방, 100=완전 폐쇄(GRIPPER_CLOSE_POS).
# 공을 놓칠 만큼만 벌리면 되는 값이라 실측 후 조정 필요.
PLACE_RELEASE_PERCENT = 40.0
PLACE_RELEASE_DURATION = 1.5
# 이동 중 바구니·다른 공을 치지 않도록 접근 높이(approach_z)에 더하는 여유.
APPROACH_Z_MARGIN = 0.06
# 바구니 바닥을 세게 치지 않도록 place_z(놓는 높이)에 더하는 여유.
PLACE_Z_MARGIN = 0.03
# 캘리브레이션이 일정하게 오른쪽(사용자 기준)으로 치우쳐서 나오는 걸 보정하는 값.
# +0.015로 시작했다가 실측해보니 오히려 더 오른쪽으로 심해져서 부호를 뒤집었다.
# 그래도 남으면 크기를 더 키운다.
Y_OFFSET_CORRECTION_M = -0.015


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
            self.controller.config.profile_velocity = PICK_PLACE_PROFILE_VELOCITY
            self.controller.move_xyz(rx, ry, travel_z, duration=3.0)
            time.sleep(SETTLE_WAIT_SEC)  # pick 하강 직전, 흔들림이 멈추길 대기

            self._gripper_open_and_wait()
            self.controller.config.profile_velocity = DESCEND_PROFILE_VELOCITY
            self.controller.move_xyz(rx, ry, cal.pick_z, duration=DESCEND_DURATION)
            self._gripper_close_and_wait()

            self.controller.config.profile_velocity = PICK_PLACE_PROFILE_VELOCITY
            self.controller.move_xyz(rx, ry, travel_z, duration=2.5)
            px, py = cal.place_pos
            self.controller.move_xyz(px, py, travel_z, duration=3.5)
            time.sleep(SETTLE_WAIT_SEC)  # place 하강 직전, 흔들림이 멈추길 대기

            self.controller.config.profile_velocity = DESCEND_PROFILE_VELOCITY
            place_target_z = cal.place_z + PLACE_Z_MARGIN
            self.controller.move_xyz(px, py, place_target_z, duration=DESCEND_DURATION)

            self.controller.set_gripper_position(
                gripper_percent_to_dxl(PLACE_RELEASE_PERCENT)
            )
            time.sleep(PLACE_RELEASE_DURATION)

            # 바구니 바닥 근처(숙인 자세)에서 바로 home()으로 보간하면 팔이
            # 스스로에 걸린다 — 안전 높이로 먼저 들어올린다. 여기서 끝내고
            # home()은 부르지 않는다: 공이 아직 있으면 watchdog이 끊기기 전에
            # 다음 탐지가 바로 여기서(이미 든 상태로) 재시도하고, 진짜 없으면
            # watchdog(check_watchdog→command_stop)이 알아서 home으로 보낸다.
            self.controller.config.profile_velocity = PICK_PLACE_PROFILE_VELOCITY
            self.controller.move_xyz(px, py, travel_z, duration=3.0)
        finally:
            self.busy = False
            self.tracking = False
            self.hit_count = 0

    def _gripper_open_and_wait(self) -> None:
        self.controller.config.profile_velocity = GRIPPER_PROFILE_VELOCITY
        self.controller.enable_torque()  # 그리퍼 속도(ms) 갱신 — 팔은 정지 상태라 안전
        self.controller.gripper_open(duration=GRIPPER_OPEN_DURATION)

    def _gripper_close_and_wait(self) -> None:
        self.controller.config.profile_velocity = GRIPPER_PROFILE_VELOCITY
        self.controller.enable_torque()
        self.controller.gripper_close(duration=GRIPPER_CLOSE_DURATION)

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
