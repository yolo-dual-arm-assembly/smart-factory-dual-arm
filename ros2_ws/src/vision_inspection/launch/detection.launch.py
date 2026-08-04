"""검사 노드(vision_inspection) + 적재 노드(omx1_loading)를 함께 띄우는 런치 파일.

사용 예:
    ros2 launch vision_inspection detection.launch.py \
        model_path:=/home/user/YOLO_Test/models/best.pt image_topic:=/image_raw
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription(
        [
            DeclareLaunchArgument("model_path", default_value="best.pt"),
            DeclareLaunchArgument("image_topic", default_value="/image_raw"),
            DeclareLaunchArgument("confidence_threshold", default_value="0.5"),
            DeclareLaunchArgument("target_class", default_value=""),
            DeclareLaunchArgument("min_confidence", default_value="0.6"),
            Node(
                package="vision_inspection",
                executable="vision_node",
                name="vision_inspection",
                output="screen",
                parameters=[
                    {
                        "model_path": LaunchConfiguration("model_path"),
                        "image_topic": LaunchConfiguration("image_topic"),
                        "confidence_threshold": LaunchConfiguration(
                            "confidence_threshold"
                        ),
                        "target_class": LaunchConfiguration("target_class"),
                    }
                ],
            ),
            Node(
                package="omx1_loading",
                executable="loading_node",
                name="omx1_loading",
                output="screen",
                parameters=[
                    {"min_confidence": LaunchConfiguration("min_confidence")}
                ],
            ),
        ]
    )
