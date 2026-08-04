# 모듈 간 통신 규격

담당 폴더가 나뉘어도 주고받는 값의 모양은 하나여야 합니다. 이 문서가 규격의
설명이고, 실행 가능한 정의는 [`common/messages.py`](../common/messages.py)와
[`common/constants.py`](../common/constants.py)에 있습니다. **문서와 코드가
어긋나면 코드가 기준입니다.** 규격을 바꿀 때는 두 곳을 같은 PR에서 고칩니다.

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

| 인터페이스 | 방식 | 위치 |
|---|---|---|
| `DetectionResult` | Topic (`/yolo/detection`) | `project_interfaces/msg/DetectionResult.msg` |

### 합의 후 추가할 것

아직 파일로 만들지 않았습니다. 팀이 규격에 합의하면
`project_interfaces/srv`, `project_interfaces/action`에 아래 초안대로
추가합니다.

```text
# srv/InspectBasket.srv — 검사 요청(Service)
int32 target_count
---
int32 total_count
int32 normal_count
int32 defect_count
bool passed
string message
```

```text
# action/LoadBalls.action — OMX 1 공 투입(Action)
int32 target_count
---
bool success
int32 loaded_count
string message
---
int32 current_count
string state
```

```text
# action/SortBasket.action — OMX 2 이송(Action)
string destination      # NORMAL 또는 REJECT
---
bool success
string message
---
string state
```

`state` 문자열은 `common.constants.RobotState` 값을 그대로 씁니다. 인터페이스가
생기면 각자 상대 코드 없이도 개발할 수 있습니다.

```bash
# OMX 2 담당자: YOLO 없이 이송 동작만 시험
ros2 action send_goal /omx2/sort_basket \
  project_interfaces/action/SortBasket "{destination: 'NORMAL'}"
```

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

```powershell
python -m system_coordinator.main_controller
```

`MainController`는 적재·검사·분류를 함수로 주입받으므로, 아직 없는 단계는 가짜
함수로 채우고 나머지 흐름을 그대로 시험할 수 있습니다.
