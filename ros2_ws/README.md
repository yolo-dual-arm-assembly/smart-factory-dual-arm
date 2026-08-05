# ROS2 워크스페이스

노드 5개로 나눈 공정 제어 워크스페이스다. **Windows에서는 빌드하지 않는다** —
Ubuntu 22.04(Humble) 또는 24.04(Jazzy)에서 아래 절차대로 빌드한다. 윈도우 개발
PC에서는 ROS2 없이 통합 GUI(`python main.py`)와 테스트만 돌린다.

## 패키지 구성

```text
ros2_ws/src/
├── common/               # 공용 상수·메시지·장치 코드 (ament_python, 노드 아님)
├── project_interfaces/   # 노드 간 메시지·서비스·액션 정의 (ament_cmake)
├── vision_inspection/    # YOLO 검사 (ament_python)   ← vision_node
├── omx1_loading/         # 적재 로봇 (ament_python)   ← loading_node
├── omx2_sorting/         # 분류 로봇 (노드 미작성)
├── system_coordinator/   # 공정 순서 제어 (노드 미작성)
└── system_monitor/       # 상태 표시·로그 (통합 GUI만 있음)
```

빌드 대상은 지금 `common`, `project_interfaces`, `vision_inspection`,
`omx1_loading` 네 개다. 나머지 세 패키지는 아직 rclpy 노드가 없어
`package.xml`을 두지 않았다. 노드를 만들 때
`package.xml`·`setup.py`·`setup.cfg`·`resource/`를 추가하면 colcon 빌드 대상이
된다.

`common`은 노드가 아니라 라이브러리 패키지다. rclpy에 의존하지 않으므로 ROS2가
없는 개발 PC에서도 그대로 import되고, colcon 빌드 후에는 다른 노드가
`<exec_depend>common</exec_depend>`로 참조한다. 폴더가 `common/common/*.py`
구조라 import 경로는 예전과 똑같이 `from common.messages import ...`이다.

## 메시지: `project_interfaces/msg/DetectionResult`

| 필드 | 의미 |
|---|---|
| `header` | 원본 이미지 프레임의 stamp/frame_id |
| `detected` | **탐지 성공/실패 flag** (물체 없음·추론 에러 모두 `false`) |
| `class_name`, `confidence` | 최고 신뢰도 탐지의 클래스/신뢰도 |
| `cx`, `cy`, `width`, `height` | bbox 중심과 크기 (픽셀) |

탐지 실패여도 **매 프레임 발행**한다. 구독자는 `detected=false`(실패)와
"메시지 자체가 안 옴"(탐지 노드 다운)을 구분할 수 있고, 후자는
`loading_node`의 워치독이 잡아서 정지 명령을 낸다.

## 서비스·액션

검사 서비스(`srv/InspectBasket.srv`)와 로봇 동작 액션
(`action/LoadBalls.action`, `action/SortBasket.action`)이 정의되어 있다.
필드 설명은
[`../docs/communication_protocol.md`](../docs/communication_protocol.md)에 있다.

**정의만 있고 서버는 아직 없다.** 지금 도는 rclpy 노드는 `vision_node`와
`loading_node`뿐이고 둘 다 토픽만 쓴다. 어느 패키지가 무엇을 구현해야 하는지는
같은 문서의 "아직 만들지 않은 것 — 서버 구현" 표에 있다.

빌드 후 정의가 잘 생성됐는지 확인한다.

```bash
ros2 interface list | grep project_interfaces
ros2 interface show project_interfaces/srv/InspectBasket
```

## 빌드 (Linux)

```bash
# 의존성
sudo apt install ros-$ROS_DISTRO-cv-bridge ros-$ROS_DISTRO-vision-opencv
pip install ultralytics==8.4.102

# 빌드 — ros2_ws/가 워크스페이스 루트다
cd ros2_ws
colcon build --symlink-install
source install/setup.bash
```

`common`도 워크스페이스의 ament 패키지라 `colcon build`가 함께 설치한다.
예전에 필요했던 `PYTHONPATH` 수동 지정은 더 이상 하지 않는다.

`object/`·`result/`·`models/` 경로를 쓰는 노드는 저장소 루트를 알아야 한다.
`ros2 launch`를 저장소 루트에서 실행하면 자동으로 찾지만, 다른 곳에서
실행한다면 환경변수로 알려 준다.

```bash
export SMART_FACTORY_PROJECT_DIR=/absolute/path/to/smart-factory-dual-arm
```

## 실행

```bash
# 카메라 드라이버 (예: USB 웹캠 → /image_raw 발행)
sudo apt install ros-$ROS_DISTRO-v4l2-camera
ros2 run v4l2_camera v4l2_camera_node

# 검사 + 적재 노드
ros2 launch vision_inspection detection.launch.py \
    model_path:=/absolute/path/to/models/best.pt \
    target_class:=robot
```

## 카메라 없이 정지 이미지로 테스트

```bash
sudo apt install ros-$ROS_DISTRO-image-publisher
ros2 run image_publisher image_publisher_node /absolute/path/to/object/bus.jpg \
    --ros-args -r image_raw:=/image_raw

# 다른 터미널에서 flag 확인
ros2 topic echo /yolo/detection
```

`detected: true`와 bbox 좌표가 흐르면 정상. 물체 없는 이미지를 주면
`detected: false`가 매 프레임 발행되는 것을 확인할 수 있다.

## 주요 파라미터

| 노드 | 파라미터 | 기본값 | 의미 |
|---|---|---|---|
| vision_node | `model_path` | `best.pt` | 가중치 경로 (절대경로 권장) |
| vision_node | `confidence_threshold` | `0.5` | YOLO conf 임계값 |
| vision_node | `target_class` | `""` | 지정 시 해당 클래스만 탐지로 인정 |
| loading_node | `min_confidence` | `0.6` | 이 값 미만이면 실패로 취급 |
| loading_node | `hit_frames` | `3` | 연속 N프레임 탐지 시 이동 시작 |
| loading_node | `miss_frames` | `5` | 연속 N프레임 실패 시 홈 복귀 |
| loading_node | `watchdog_sec` | `1.0` | 이 시간 동안 메시지 없으면 정지 |

## 실제 로봇팔 연결

`loading_node.py`의 `command_move` / `command_home` / `command_stop`은 로그만
찍는 자리표시자다. 같은 패키지의 `pick_ball.py`·`imitation_control.py`가 이미
Dynamixel 제어를 하고 있으므로, 노드에서 그 실행기를 호출하도록 바꾸는 것이
다음 단계다. 픽셀 좌표(`cx`, `cy`)를 로봇 좌표로 바꾸는 변환은 같은 패키지의
`coordinate_transform.py`에 있다.
