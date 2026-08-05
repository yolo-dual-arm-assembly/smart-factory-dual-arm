# 모듈 간 통신 규격

담당 폴더가 나뉘어도 주고받는 값의 모양은 하나여야 합니다. 이 문서가 규격의
설명이고, 실행 가능한 정의는
[`common/messages.py`](../ros2_ws/src/common/common/messages.py)와
[`common/constants.py`](../ros2_ws/src/common/common/constants.py)에 있습니다.
**문서와 코드가 어긋나면 코드가 기준입니다.** 규격을 바꿀 때는 두 곳을 같은
PR에서 고칩니다.

## 왜 dict가 아니라 dataclass인가

`result["reslut"]` 같은 오타나 빠진 키는 dict로는 통합 단계에서야 드러납니다.
dataclass는 만든 사람 자리에서 바로 실패하고, 편집기 자동완성도 됩니다. 다른
프로세스나 ROS2로 보낼 때만 `to_dict()`로 바꿔 쓰세요.

```python
from common.messages import InspectionResult

result = InspectionResult.from_counts(total_count=3, defect_count=0)
result.result      # RobotState.PASS
result.to_dict()   # {"total_count": 3, "defect_count": 0, "result": "PASS"}
```

## 검사 결과 — 2번(비전) → 1번(통합)

| 필드 | 타입 | 설명 |
|---|---|---|
| `total_count` | int | 바구니 안 공 전체 개수 |
| `defect_count` | int | 그중 불량 개수 |
| `result` | RobotState | `PASS` 또는 `REJECT` |

판정 기준은 `InspectionResult.from_counts()` 한 곳에만 둡니다. 담당자별로
`if defect_count > 0` 같은 조건을 각자 적으면 기준이 갈라집니다.

`InspectBasket.srv`의 `normal_count`·`passed`도 각자 계산하지 말고 파생 속성을
그대로 씁니다.

```python
response.total_count  = result.total_count
response.normal_count = result.normal_count   # total - defect
response.defect_count = result.defect_count
response.passed       = result.is_pass
```

## 좌표 변환 결과 — 3번(보정) → 4·5번(로봇)

| 필드 | 타입 | 설명 |
|---|---|---|
| `x`, `y`, `z` | float | 로봇 기준 좌표(미터) |

화면 픽셀 좌표를 로봇 좌표로 바꾸는 구현은
[`omx1_loading/coordinate_transform.py`](../ros2_ws/src/omx1_loading/omx1_loading/coordinate_transform.py)에
있습니다.

## 로봇 상태 — 4·5번(로봇) → 1번(통합)

| 필드 | 타입 | 설명 |
|---|---|---|
| `robot_id` | str | `OMX_1`(적재) 또는 `OMX_2`(분류) |
| `state` | RobotState | 아래 상태값 중 하나 |
| `success` | bool | 동작 성공 여부 |
| `message` | str | 실패 이유 등 사람이 읽을 설명 |

## 공정 상태값

```text
IDLE → LOADING → LOADING_COMPLETE → INSPECTING → PASS/REJECT → MOVING → COMPLETE → IDLE
                                          └────────── ERROR ──────────┘
```

문자열을 직접 적지 말고 `common.constants.RobotState`를 import해서 씁니다.
허용되는 전이는
[`system_coordinator/state_machine.py`](../ros2_ws/src/system_coordinator/system_coordinator/state_machine.py)의
`ALLOWED_TRANSITIONS`에 정의되어 있고, 규칙에 없는 전이는 예외로 막힙니다.

## ROS2에서 무엇으로 통신하나

| 통신 대상 | 방식 | 이유 |
|---|---|---|
| OMX 장시간 동작 | Action | 진행 상태와 성공 여부를 함께 받을 수 있음 |
| YOLO 1회 검사 | Service | 요청하면 결과를 바로 반환 |
| 로봇 현재 상태 | Topic | 상태를 계속 흘려보냄 |
| GUI·로그 데이터 | Topic | 여러 노드가 동시에 구독 |

### 지금 있는 것

인터페이스 4종이 모두 정의되어 있습니다. 파일이 규격의 기준이고, 이 표는
어디에 무엇이 있는지만 알려 줍니다.

| 인터페이스 | 방식 | 이름 | 위치 |
|---|---|---|---|
| `DetectionResult` | Topic | `/yolo/detection` | `project_interfaces/msg/DetectionResult.msg` |
| `InspectBasket` | Service | `/vision/inspect_basket` | `project_interfaces/srv/InspectBasket.srv` |
| `LoadBalls` | Action | `/omx1/load_balls` | `project_interfaces/action/LoadBalls.action` |
| `SortBasket` | Action | `/omx2/sort_basket` | `project_interfaces/action/SortBasket.action` |

`state` 문자열은 `common.constants.RobotState` 값을 그대로 씁니다.

### 아직 만들지 않은 것 — 서버 구현

인터페이스 **정의**는 있지만 이 서비스·액션을 실제로 제공하는 노드는 아직
없습니다. 현재 rclpy 노드는 `vision_node`(토픽 발행)와
`loading_node`(토픽 구독)뿐이고, 둘 다 위 서비스·액션을 쓰지 않습니다.

| 인터페이스 | 서버를 만들 곳 | 담당 |
|---|---|---|
| `InspectBasket` | `vision_inspection` — 집계는 `inspection_logic.count_detections()` 재사용 | 2번 |
| `LoadBalls` | `omx1_loading` — 동작은 `pick_ball.py` 재사용 | 3번 |
| `SortBasket` | `omx2_sorting` — 노드부터 만들어야 함 | 5번 |

정의가 생겼으므로 각자 상대 코드 없이도 개발할 수 있습니다. 상대편이 없으면
CLI로 먼저 시험합니다.

```bash
# OMX 2 담당자: YOLO 없이 이송 동작만 시험
ros2 action send_goal /omx2/sort_basket \
  project_interfaces/action/SortBasket "{destination: 'NORMAL'}"
```

### `/yolo/detection`과 `InspectBasket`은 다른 일을 한다

두 경로를 같은 것으로 착각하기 쉬우니 구분해 둡니다.

| | `/yolo/detection` (Topic) | `InspectBasket` (Service) |
|---|---|---|
| 언제 | 매 프레임 계속 | 요청할 때 한 번 |
| 무엇을 | 최고 신뢰도 물체 **1개**의 bbox | 바구니 안 공 **전체 개수**와 불량 수 |
| 쓰는 곳 | 팔이 물체를 실시간 추종 (`loading_node`) | 공정의 PASS/REJECT 판정 (coordinator) |

토픽은 "지금 저기 뭐가 보인다"를, 서비스는 "이 바구니 합격인가"를 답합니다.
토픽 결과를 세어서 검사 결과로 쓰면 안 됩니다 — 같은 공을 여러 프레임에서
중복으로 세게 됩니다.

## 프로세스 안에서 쓰는 토픽 이름

ROS2를 붙이기 전에는
[`system_coordinator/communication.py`](../ros2_ws/src/system_coordinator/system_coordinator/communication.py)의
`LocalChannel`로 같은 흐름을 시험합니다. 토픽 이름은 그 파일에 상수로 있습니다.

| 상수 | 토픽 | 보내는 값 |
|---|---|---|
| `TOPIC_INSPECTION` | `inspection/result` | `InspectionResult` |
| `TOPIC_ROBOT_STATUS` | `robot/status` | `RobotStatus` |
| `TOPIC_TARGET_POSITION` | `robot/target_position` | `RobotPosition` |

같은 값을 두 곳에서 다르게 정의하지 않도록, ROS2 인터페이스를 고치면 이 문서와
`common/messages.py`도 같은 PR에서 고칩니다.

## 장비가 없을 때 연결 시험하기

담당자 코드가 완성되지 않아도 통합 흐름은 먼저 돌려볼 수 있습니다.

```bash
python -m system_coordinator.main_controller
```

`MainController`는 적재·검사·분류를 함수로 주입받으므로, 아직 없는 단계는 가짜
함수로 채우고 나머지 흐름을 그대로 시험할 수 있습니다.
