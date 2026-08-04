# system_coordinator — 전체 순서 제어 (담당: 5번)

각 노드를 엮어 하나의 공정으로 만듭니다. 노드끼리는 서로를 import하지 않고,
연결은 여기서만 합니다.

| 파일 | 역할 |
|---|---|
| `main_controller.py` | 적재 → 검사 → 분류 한 사이클 진행 |
| `state_machine.py` | 공정 상태 전이 규칙 (`IDLE`…`COMPLETE`) |
| `communication.py` | 모듈 간 메시지 통로와 토픽 이름 |
| (노드) | 아직 rclpy 노드는 없습니다. 흐름 로직만 있고, 여기에 `coordinator_node.py`를 추가하면 됩니다 |

## 장비 없이 흐름 확인

```powershell
python -m system_coordinator.main_controller
```

`MainController`는 적재·검사·분류 단계를 함수로 주입받습니다. 아직 없는 단계는
가짜 함수로 채우고 나머지를 그대로 시험할 수 있습니다.

```python
MainController(
    load_basket=lambda: RobotStatus(RobotId.LOADING, RobotState.LOADING_COMPLETE),
    inspect=lambda: InspectionResult.from_counts(3, 0),
    sort_basket=lambda result: RobotStatus(RobotId.SORTING, RobotState.COMPLETE),
).run_cycle()
```

## 통합 GUI

```powershell
python main.py
```

`ui/`는 Tkinter 화면 조립만 담당합니다. 계산·파일 처리·장비 제어는 각 담당
폴더의 함수를 부르고, 콜백 안에 로직을 넣지 않습니다.

## 규격 관리

`common/messages.py`와 `docs/communication_protocol.md`가 규격의 단일 출처입니다.
담당자가 반환값을 바꾸고 싶어 하면 먼저 이 두 파일을 같은 PR에서 고칩니다.
