# omx2_sorting — 두 번째 OMX·분류 (담당: 4번)

검사 결과에 따라 바구니를 통과 라인과 재작업 라인으로 나눕니다. PASS/REJECT
동작은 구현돼 있고, 검사 위치로의 이동(`move_basket.py`)만 남아 있습니다.

| 파일 | 역할 | 상태 |
|---|---|---|
| `move_basket.py` | 바구니를 검사 위치로 이동 | 구현 필요 |
| `motion_runner.py` | PASS/REJECT 공통 실행기 | 구현 완료 |
| `pass_motion.py` | PASS 바구니 처리(`motion_runner` 호출) | 구현 완료 |
| `reject_motion.py` | REJECT 바구니 처리(`motion_runner` 호출) | 구현 완료 |
| `waypoints.py` | 웨이포인트 JSON 실행 전 검증 | 구현 완료 |
| `teach_motion.py` | 웨이포인트 교시 CLI | 구현 완료 |
| `manual_motion_check.py` | PASS/REJECT 실제 장비 수동 확인 CLI | 구현 완료 |

## 시작하는 법

로봇 통신은 새로 만들지 말고 `common` 패키지의 `omx_controller.py`의 `OmxController`를
씁니다. 이동 시퀀스 예시는 `omx1_loading/imitation_control.py`에 있습니다.

```python
from common.constants import RobotId, RobotState
from common.messages import RobotStatus
from omx2_sorting.move_basket import open_controller

controller = open_controller()          # 포트는 자동 탐색
# ... 이동 구현 ...
return RobotStatus(RobotId.SORTING, RobotState.COMPLETE)
```

## 규격

- 모든 함수는 `RobotStatus`를 반환합니다. 실패는 예외 대신
  `success=False`와 `message`로 알립니다.
- 검사 결과 판정을 다시 하지 않습니다. `InspectionResult.is_pass`만 봅니다.

## 로봇이 없을 때

통합 담당자와 붙여 보려면 실제 이동 대신 `RobotStatus`만 돌려주는 가짜 함수로
`system_coordinator.main_controller.MainController`에 주입해 흐름을 먼저 확인하세요.
