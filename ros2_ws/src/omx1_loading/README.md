# omx1_loading — 첫 번째 OMX·적재 (담당: 3번)

공을 집어 바구니에 담는 로봇 노드입니다. Dynamixel 통신 자체는 레포 루트의
[`common/omx_controller.py`](../common/common/omx_controller.py)를 그대로 씁니다.

| 파일 | 역할 |
|---|---|
| `loading_node.py` | ROS2 노드: 탐지 flag 구독 → 디바운싱·워치독 → 팔 명령 |
| `coordinate_transform.py` | 픽셀 ↔ 로봇 좌표 변환 (담당 3번) |
| `camera_calibration.py` | 화면 클릭 보정 창 |
| `pick_ball.py` | 탐지 좌표를 보정값으로 변환해 집으러 가는 실행기 |
| `imitation_control.py` | 교시(모방)값 보간으로 이동하는 실행기 |
| `teaching.py` | 화면 좌표와 실제 관절값 교시 데이터·보간 |
| `teaching_window.py` | 교시 모드 Tkinter 창 |
| `run_vision_pick.py` | 보정 기반 이동 CLI |
| `run_imitation.py` | 교시 기반 이동 CLI |
| `config/` | 보정·교시 데이터 (장비별 값이라 Git에 올리지 않음) |

## 실행

```powershell
python -m omx1_loading.run_imitation
python -m omx1_loading.run_vision_pick --port COM10
```

GUI에서는 `OMX 비전 제어` 패널의 `2. Mouse 관절 교시 모드` → `3. 교시값으로
Mouse 이동` 순서로 씁니다.

## 규격

- 상태 보고는 `RobotStatus(RobotId.LOADING, RobotState.LOADING_COMPLETE)` 형태로
  coordinator에 돌려줍니다.
- 목표 좌표는 `RobotPosition`으로 받습니다. 픽셀 좌표를 직접 받지 않습니다.

## 주의

- 교시점은 4개 이상이어야 하고, 서로 둘러싸인 영역을 만들어야 자동 이동이
  허용됩니다. 화면 9곳(모서리·변·중앙)에 두는 것을 권장합니다.
- 카메라 위치나 해상도가 바뀌면 교시 데이터를 다시 만들어야 합니다.
