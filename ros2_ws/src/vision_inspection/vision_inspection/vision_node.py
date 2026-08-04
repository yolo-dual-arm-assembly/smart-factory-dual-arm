"""카메라 이미지 토픽을 구독해 YOLO 추론 후 DetectionResult를 발행하는 노드.

탐지 실패(물체 없음/추론 에러)여도 매 프레임 detected=False로 발행한다.
구독자가 '실패'와 '탐지 노드 다운'을 구분할 수 있어야 하기 때문이다.
"""
from __future__ import annotations

import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image
from ultralytics import YOLO

from project_interfaces.msg import DetectionResult


class YoloDetectorNode(Node):
    def __init__(self) -> None:
        super().__init__("vision_inspection")
        self.declare_parameter("model_path", "best.pt")
        self.declare_parameter("confidence_threshold", 0.5)
        self.declare_parameter("image_topic", "/image_raw")
        # 비워두면 모든 클래스를 대상으로 하고, 지정하면 해당 클래스만 탐지로 인정한다.
        self.declare_parameter("target_class", "")

        model_path = str(self.get_parameter("model_path").value)
        self.conf_threshold = float(self.get_parameter("confidence_threshold").value)
        self.target_class = str(self.get_parameter("target_class").value)
        image_topic = str(self.get_parameter("image_topic").value)

        self.model = YOLO(model_path)
        self.bridge = CvBridge()
        self.publisher = self.create_publisher(DetectionResult, "/yolo/detection", 10)
        self.subscription = self.create_subscription(
            Image, image_topic, self.on_image, qos_profile_sensor_data
        )
        self.get_logger().info(
            f"model={model_path} conf={self.conf_threshold} "
            f"image_topic={image_topic} target_class={self.target_class or '(all)'}"
        )

    def on_image(self, image_msg: Image) -> None:
        msg = DetectionResult()
        msg.header = image_msg.header
        msg.detected = False
        try:
            frame = self.bridge.imgmsg_to_cv2(image_msg, desired_encoding="bgr8")
            result = self.model(frame, conf=self.conf_threshold, verbose=False)[0]
            best = self.pick_best(result)
            if best is not None:
                confidence, class_name, box = best
                cx, cy, width, height = box.xywh[0].tolist()
                msg.detected = True
                msg.class_name = class_name
                msg.confidence = confidence
                msg.cx = float(cx)
                msg.cy = float(cy)
                msg.width = float(width)
                msg.height = float(height)
        except Exception as exc:  # 추론 에러도 '탐지 실패'로 통일해 발행한다
            self.get_logger().warning(f"inference failed: {exc}")
        self.publisher.publish(msg)

    def pick_best(self, result):
        """target_class에 맞는 박스 중 신뢰도가 가장 높은 것을 고른다."""
        boxes = result.boxes
        if boxes is None or len(boxes) == 0:
            return None
        candidates = []
        for box in boxes:
            class_name = result.names[int(box.cls.item())]
            if self.target_class and class_name != self.target_class:
                continue
            candidates.append((float(box.conf.item()), class_name, box))
        if not candidates:
            return None
        return max(candidates, key=lambda item: item[0])


def main(args=None) -> None:
    rclpy.init(args=args)
    node = YoloDetectorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
