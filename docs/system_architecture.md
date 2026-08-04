# 시스템 구조

프로그램을 노드 5개로 나눈다. 각 노드는 독립된 파이썬 프로그램이고, 서로는
ROS2 인터페이스로만 데이터를 주고받는다.

```text
                     coordinator (system_coordinator)
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
   OMX 1 공 투입          YOLO 검사 요청        OMX 2 정상/불량 이송
   (omx1_loading)      (vision_inspection)     (omx2_sorting)
        └─────────────────────┼─────────────────────┘
                              │ 상태·로그
                       system_monitor
```

## 공정 흐름

1. coordinator가 OMX 1에 공 투입 명령
2. OMX 1이 설정 개수만큼 투입
3. OMX 1이 작업 완료 응답
4. coordinator가 YOLO 검사 요청
5. vision이 개수와 결함 여부 반환
6. coordinator가 PASS/REJECT 판단
7. OMX 2에 정상 또는 불량 구역 이송 명령
8. OMX 2가 이송 완료 응답

## 패키지와 담당

레포는 하나의 ROS2 워크스페이스(`ros2_ws/`)이고, 공용 파이썬 코드만 레포
루트의 `common/`에 둔다.

| 패키지 | 담당 | 현재 들어 있는 것 |
|---|---|---|
| `project_interfaces` | 5번 | `msg/DetectionResult.msg` (srv·action은 합의 후 추가) |
| `vision_inspection` | 1·2번 | `vision_node.py`(ROS2 노드), `inspection_logic.py`, `analysis.py`, `models.py`, `training.py`, `train.py`, `detect.py`, `config/data.yaml` |
| `omx1_loading` | 3번 | `loading_node.py`(ROS2 노드), `coordinate_transform.py`, `camera_calibration.py`, `pick_ball.py`, `imitation_control.py`, `teaching.py`, `teaching_window.py`, CLI 2개 |
| `omx2_sorting` | 4번 | `move_basket.py`, `pass_motion.py`, `reject_motion.py` (뼈대) |
| `system_coordinator` | 5번 | `main_controller.py`, `state_machine.py`, `communication.py` |
| `system_monitor` | 5번 | 통합 운영 GUI(`ui/`) |
| `common/` (루트) | 5번 | `constants.py`, `messages.py`, `logger.py`, `camera.py`, `serial_ports.py`, `omx_controller.py`, `bootstrap.py` |

`vision_inspection` 안에서 1번(모델 학습·데이터셋)과 2번(카메라·검사 서비스)이
파일 단위로 나뉜다. 학습 쪽은 `train.py`·`training.py`·`models.py`, 검사 쪽은
`vision_node.py`·`inspection_logic.py`다.

## ROS2 노드 상태

지금 rclpy 노드가 있는 패키지는 둘뿐이다.

| 패키지 | 노드 | 상태 |
|---|---|---|
| `vision_inspection` | `vision_node` | 이미지 토픽 구독 → 추론 → `/yolo/detection` 발행 |
| `omx1_loading` | `loading_node` | 탐지 flag 구독 → 디바운싱·워치독 → 팔 명령(자리표시자) |
| `omx2_sorting` | — | 노드 미작성 |
| `system_coordinator` | — | 노드 미작성 (`main_controller.py`가 흐름 로직만 담당) |
| `system_monitor` | — | 노드 미작성 (GUI만 존재) |

노드가 없는 패키지에는 `package.xml`을 두지 않았다. 노드를 만들 때
`package.xml`·`setup.py`·`setup.cfg`·`resource/`를 추가하면 colcon 빌드 대상이
된다.

## 지켜야 할 방향

- 노드끼리 파이썬 import로 엮지 않는다. 노드 간 연결은 ROS2 인터페이스로만 한다.
  같은 패키지 안의 모듈끼리는 자유롭게 import한다.
- 값이 패키지 경계를 넘으면 `common/messages.py`의 dataclass 규격을 쓴다.
  ROS2 메시지로 나갈 때는 `to_dict()`로 바꾼다.
- 상태 문자열은 각자 적지 않고 `common/constants.py`의 `RobotState`를 쓴다.
- 계산·검증 로직은 노드 콜백이나 GUI 콜백 안에 넣지 않는다. 그래야 ROS2나
  장비 없이 `tests/`에서 검사할 수 있다.
- 새 카메라 사용 기능은 `common/camera.py`의 캡처 함수를 재사용한다.
- 새 YOLO 모델은 `vision_inspection/models.py`에 등록한다.

## 운영체제 대응

리눅스와 윈도우는 같은 코드로 실행한다. ROS2 빌드는 리눅스에서만 하고, 윈도우
개발 PC에서는 ROS2 없이 GUI와 로직·테스트를 돌린다.

- import 경로: ROS2 패키지는 `pkg/pkg/*.py` 구조라 바깥쪽 패키지 폴더가 import
  경로다. `common/bootstrap.py`의 `ensure_workspace_path()`가 `main.py` 실행
  시점에 이 경로들을 등록하고, 테스트는 `pyproject.toml`의 `pythonpath`가
  담당한다.
- 시리얼 포트: 이름 규칙이 `/dev/ttyACM0`과 `COMx`로 달라, 연결된 포트를
  조회해 USB 장치를 고른다. 조회 결과가 없을 때만 OS별 기본값을 쓰고,
  GUI 입력칸과 `--port` 옵션으로 언제든 직접 지정할 수 있다.
- 카메라 목록: 리눅스는 `/sys/class/video4linux`에서 장치 이름을 그대로 읽지만,
  윈도우에는 같은 목록이 없어 인덱스를 직접 열어 확인한다. 이름은 장치 관리자
  조회로 보완하되, 개수가 어긋나면 잘못 짝지어질 수 있으므로 번호만 남긴다.
  카메라가 둘 이상이면 어떤 장치를 쓸지는 사용자가 GUI에서 고른다.
- 한글 글꼴: 설치된 글꼴이 OS마다 다르므로 후보를 우선순위대로 두고 실제로
  설치된 글꼴을 고른다. 설치되지 않은 이름을 폴백으로 쓰면 Tk가 조용히 다른
  글꼴로 대체하므로, 폴백도 시스템이 이미 쓰는 글꼴에서 가져온다.

## 실행 방식

| 목적 | 명령 |
|---|---|
| 통합 운영 GUI | `python main.py` (레포 루트) |
| 공정 흐름 확인(장비 없이) | `python -m system_coordinator.main_controller` |
| 학습 | `python -m vision_inspection.train` |
| ROS2 노드 | `ros2 launch vision_inspection detection.launch.py` (리눅스, colcon 빌드 후) |

`python -m ...` 형태는 패키지 경로가 등록되어 있어야 한다. 한 번
`pip install -e .`를 실행하거나 `PYTHONPATH`에 `ros2_ws/src/<패키지>`를 넣는다.

## 통합 순서

각자 자기 패키지만 두 달 개발한 뒤 마지막에 합치면 거의 반드시 실패한다.
장비가 없어도 흐름은 먼저 연결할 수 있다.

1. 인터페이스 확정 → `project_interfaces`와 `common/messages.py`
2. 가짜 데이터로 흐름 연결 → `python -m system_coordinator.main_controller`
3. YOLO 검사 결과 연결 → `vision_inspection/inspection_logic.py`
4. 첫 번째 OMX 연결 → `omx1_loading`
5. 두 번째 OMX 연결 → `omx2_sorting`
6. 실제 장비 통합과 오류 수정

매주 최소 한 번은 `main`에 병합해 연결 테스트를 한다.
