cmake_minimum_required(VERSION 3.8)
project(project_interfaces)

find_package(ament_cmake REQUIRED)
find_package(std_msgs REQUIRED)
# action 정의는 goal_id·상태 필드 때문에 action_msgs가 있어야 생성된다.
find_package(action_msgs REQUIRED)
find_package(rosidl_default_generators REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/DetectionResult.msg"
  "srv/InspectBasket.srv"
  "action/LoadBalls.action"
  "action/SortBasket.action"
  DEPENDENCIES std_msgs action_msgs
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
