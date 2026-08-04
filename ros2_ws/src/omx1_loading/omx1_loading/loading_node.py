"""DetectionResult를 구독해 로봇팔 명령을 결정하는 예시 노드.

실제 팔 구동부(MoveIt2, 제조사 드라이버 등)는 command_move/command_home/command_stop
안쪽을 교체해서 연결한다. 이 노드가 보여주는 것은 flag 처리 패턴 세 가지다:
- 디바운싱: 연속 hit_frames 프레임 탐지됐을 때만 이동 시작 (오탐 1프레임에 반응 금지)
- 실패 유예: 연속 miss_frames 프레임 실패했을 때만 홈 복귀 (한 프레임 놓침에 중단 금지)
- 워치독: watchdog_sec 동안 메시지가 없으면 탐지 노드 다운으로 간주하고 정지
"""
from __future__ import annotations

import rclpy
from rclpy.node import Node

from project_interfaces.msg import DetectionResult


class ArmControllerNode(Node):
    def __init__(self) -> None:
        super().__init__("omx1_loading")
        self.declare_parameter("min_confidence", 0.6)
        self.declare_parameter("hit_frames", 3)
        self.declare_parameter("miss_frames", 5)
        self.declare_parameter("watchdog_sec", 1.0)

        self.min_confidence = float(self.get_parameter("min_confidence").value)
        self.hit_frames = int(self.get_parameter("hit_frames").value)
        self.miss_frames = int(self.get_parameter("miss_frames").value)
        self.watchdog_sec = float(self.get_parameter("watchdog_sec").value)

        self.hit_count = 0
        self.miss_count = 0
        self.tracking = False
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

        if msg.detected and msg.confidence >= self.min_confidence:
            self.hit_count += 1
            self.miss_count = 0
            if self.tracking:
                self.command_move(msg)
            elif self.hit_count >= self.hit_frames:
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

    # --- 아래 세 메서드를 실제 로봇팔 인터페이스로 교체한다 ---

    def command_move(self, msg: DetectionResult) -> None:
        self.get_logger().info(
            f"MOVE → ({msg.cx:.0f}, {msg.cy:.0f}) "
            f"{msg.class_name} conf={msg.confidence:.2f}"
        )

    def command_home(self) -> None:
        self.get_logger().info("HOME — 탐지 끊김, 대기 자세로 복귀")

    def command_stop(self) -> None:
        self.get_logger().warning(
            f"STOP — {self.watchdog_sec}s 동안 탐지 메시지 없음 (탐지 노드 다운 의심)"
        )


def main(args=None) -> None:
    rclpy.init(args=args)
    node = ArmControllerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
