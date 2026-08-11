# ROS2 이관 로드맵

## 전략

지금은 통합 공정을 Tkinter GUI(`system_monitor`)로 완성하고, 이후 같은 로직을
ROS2 서버(`InspectBasket` 서비스, `LoadBalls`/`SortBasket` 액션, coordinator
노드)로 올린다. 이 전략은 리포 설계와 일치한다:

- GUI → 노드 패키지 방향의 import는 허용된다 (AGENTS.md의 `system_monitor` 예외).
- 패키지 경계를 넘는 값은 `common.messages` dataclass(`InspectionResult`,
  `RobotStatus`)로 통일돼 있어 ROS2 메시지와 1:1 매핑이 쉽다.
- `project_interfaces`의 srv/action 정의가 이미 존재한다.

핵심 원칙: **ROS2 서버는 얇은 래퍼여야 한다.** 스테이지 로직은 각 소유
패키지의 "진입점 함수"에 두고, GUI와 미래의 ROS2 서버가 같은 함수를 호출한다.
이 문서는 그 진입점이 어디에 있어야 하는지, 지금 코드와의 간극이 무엇인지를
기록한다.

## 현재 상태 (2026-08-11 기준)

- rclpy 노드는 2개뿐: `vision_node`(YOLO 추론 → `/yolo/detection`, 프레임당
  최고 신뢰도 박스 1개만 — 트래킹용이지 바구니 개수 검사용이 아님),
  `loading_node`(디바운싱·워치독 골격, 팔 명령 3개는 로그 자리표시자).
- 서비스·액션 서버는 0개. srv/action을 import하는 코드도 없다.
- 통합 공정(c210a06)은 GUI 워커 스레드가 노드 패키지를 직접 import해 실행하는
  경로다. ROS2를 전혀 거치지 않는다.
- `omx2_sorting`·`system_coordinator`는 `package.xml`/`setup.py`가 없어 colcon
  대상이 아니다 (TODO P1에 등록됨).

## 이관을 막는 구조 부채 4개

서버를 만들기 전에 해소해야 하는 항목. 해소 전까지는 GUI 동작에 영향 없음.

1. **분류 진입점이 GUI 패키지에 있다.**
   `execute_sorting_motion()`/`check_sorting_motors()`가
   `system_monitor/ui/sorting_panel.py`에 있다. 노드 패키지는 `system_monitor`를
   import할 수 없으므로(colcon 설치본에 GUI가 없음) `SortBasket` 서버 작성 전에
   `omx2_sorting`으로 이동해야 한다.
2. **적재에 공개 1사이클 API가 없다.**
   GUI가 `OmxVisionRunner`의 비공개 메서드 `_execute_action`을 서브클래스로
   오버라이드해 "한 번 집으면 종료"를 구현한다(`viewer.py`의
   `OneCycleVisionRunner`). `run()`은 `None`을 반환하고 실패를 예외로만 알리며
   적재 개수 카운터가 없다 — `LoadBalls.action`의
   `loaded_count`/`current_count`를 채울 수 없다.
3. **검사에 호출 가능한 진입점이 없다.**
   판정은 GUI `CameraFeed` 캡처 스레드 안에서 계산되고, 통합 공정은
   `viewer._wait_for_fresh_inspection()`이 스냅샷을 0.1초 간격으로 최대 15초
   폴링해 긁어온다. "요청 → 안정화된 판정 응답" 형태의 함수가 없어
   `InspectBasket` 서비스로 만들 수 없다.
4. **시퀀싱이 GUI 워커에 중복돼 있다.**
   `viewer._integrated_worker()`가 적재→검사→분류 순서, 취소, 부분 완료를 직접
   구현한다. 테스트된 `system_coordinator.MainController`(콜백 3개 주입,
   상태 기계, 오류 래치)는 사용되지 않는다. 미래의 coordinator 노드는
   `MainController`에 액션 클라이언트 클로저를 주입하는 형태가 된다.

## 인터페이스별 이관 계획

서버 = 아래 진입점을 감싸는 래퍼. 진입점 함수는 아직 없으며, 착수 시
"작업 순서" 절의 단계에서 만든다.

| 인터페이스 | 서버 패키지 | 감쌀 진입점 (신설 대상) | 래퍼가 하는 일 |
|---|---|---|---|
| `LoadBalls.action` | `omx1_loading` | `loading_runner.load_balls(target_count, *, port, camera_index, model_path, cancel, on_progress, show_window=False) -> RobotStatus` | goal→인자, `on_progress`→feedback, `RobotStatus`→result 복사 |
| `InspectBasket.srv` | `vision_inspection` | `verdict_wait.await_verdict(poll, *, timeout_sec, cancel, poll_interval_sec) -> InspectionResult \| None` | 노드 소유 프레임 루프로 `poll` 클로저 구성, 응답 필드 복사 |
| `SortBasket.action` | `omx2_sorting` | `sort_basket.sort_basket(inspection, *, port, cancel) -> RobotStatus` | `destination`→합성 `InspectionResult` 변환, result 복사 |
| coordinator 노드 | `system_coordinator` | 기존 `MainController(load_basket, inspect, sort_basket)` | 콜백 3개를 액션 클라이언트 클로저로 주입 |

진입점 설계 요점:

- **`load_balls()`**: `OmxVisionRunner`에 `max_cycles`/`on_cycle_complete`/
  `show_window` 공식 지원을 추가하고(비공개 메서드 서브클래싱 제거), 예외를
  `RobotStatus(success=False, message=...)`로 변환해 절대 raise하지 않는
  래퍼 모듈을 둔다. 취소는 호출자의 `threading.Event`를 감시해
  `runner.request_stop()` + `controller.request_stop()`을 호출하는 방식 —
  러너 내부 stop 이벤트와 공유하면 안 된다(사이클 완료 시 자기 자신에게
  stop을 걸기 때문). `cv2.imshow` 창은 `show_window` 플래그로 선택화한다
  (ROS2 노드는 headless).
- **`await_verdict()`**: `stability.VerdictStabilizer`(시계·카메라 주입식 순수
  로직)는 그대로 재사용하고, "안정화된 판정이 나올 때까지 대기"만 함수로
  분리한다. GUI는 `CameraFeed.snapshot()`을 읽는 `poll` 클로저를, ROS2 서비스는
  자체 프레임 루프 기반 `poll`을 공급한다. `stability.py` 자체에 넣지 않는다
  (그 모듈은 벽시계를 모르는 순수 계약 유지).
- **`sort_basket()`**: 현재 `viewer._run_sorting_once()`의 컨트롤러 생성→연결→
  실행→해제 수명 관리를 그대로 옮긴다. `pass_motion.run`/`reject_motion.run`과
  같은 계약(절대 raise하지 않고 `RobotStatus.success`로 보고)을 따른다.
- **coordinator**: `MainController`에 `cancel`/`on_state` 파라미터를 하위호환으로
  추가하는 일은 노드를 실제로 만들 때 한다(goal 취소·feedback 정책이 요구사항을
  결정하므로). 상태 기계에 "단계 건너뛰기" 전이는 추가하지 않는다 — 건너뛰기는
  GUI 데모의 개념이고, 자동 공정은 전체 사이클이 전제다.

## 와이어 매핑 규약 (서버 작성 시 따를 결정)

- **`target_count`**: srv의 `0` = 개수 검사 안 함 ↔ Python의 `None`.
  `inspection_logic.UNSET`("설정 파일 값 사용")은 Python 전용 편의값으로 와이어
  표현이 없다 — 서비스 요청에는 항상 명시값(0 또는 양수)이 온다.
- **`SortBasket.goal.destination`**: `"NORMAL"`/`"REJECT"` 문자열 ↔ 합성
  `InspectionResult`(PASS/REJECT 판정만 유효, 개수는 형식값). 현재
  `sorting_panel.MANUAL_PASS`/`MANUAL_REJECT` 상수가 같은 합성 방식의 선례다.
  `"NORMAL"`은 `RobotState` 멤버가 아니므로 변환 함수에서만 다룬다.
- **`LoadBalls.feedback.state`**: `OmxVisionRunner.State`(WAIT/APPROACH/DESCEND/
  GRAB/LIFT/PLACE/RELEASE/HOME)와 `common.constants.RobotState`는 어휘가 다르다.
  feedback에는 `RobotState` 값을 쓰기로 돼 있으므로 러너 상태를 그대로 내보내지
  말고 매핑(대부분 `LOADING`)을 거친다.
- **`LoadBalls.result.loaded_count`**: `RobotStatus`에 개수 필드가 없고
  `common`은 보호 경로다. 서버가 `on_progress` 콜백으로 받은 마지막 값을
  result에 채운다 — `common.messages` 변경 불필요.
- **`InspectBasket` 응답**: `InspectionResult`의 `total_count`/`normal_count`/
  `defect_count`/`is_pass`가 1:1 대응. 단, TODO P1의 이물질 `normal_count` 음수
  문제를 서버 작성 전에 해소할 것 (`foreign_count` 분리 권장).

## 작업 순서 (착수 시)

패키지 단위 4단계. 각 단계는 단독으로 빌드·테스트 가능하고, 단계 완료 후에도
GUI 동작은 동일하다. ①~③은 순수 추가라 GUI가 기존 경로를 계속 쓴다.

1. **`omx2_sorting`**: `sort_basket.py` 신설 —
   `execute_sorting_motion`/`check_sorting_motors` 이동 +
   `sort_basket()`/`inspection_for_destination()` 추가.
   테스트: dispatch 분기, 모터 부재 시 오류, 연결 실패 시 ERROR status, 취소
   전달 (기존 `tests/test_omx_waypoints.py`의 RecordingController fake 패턴).
2. **`vision_inspection`**: `verdict_wait.py` 신설 — `await_verdict()`.
   테스트: 즉시 확정, settling 무시, 타임아웃, 취소, poll 예외 전파
   (스크립트된 poll 클로저, 짧은 타임아웃).
3. **`omx1_loading`**: `OmxVisionRunner`에 `max_cycles`/`on_cycle_complete`/
   `show_window` 추가(기본값 유지) + `loading_runner.py`의 `load_balls()` 신설.
   테스트: 사이클 카운트·자동 정지, 부분 스테이지 미카운트, 취소 시 러너 미생성,
   성공/조기 종료/취소 status (기존 `tests/test_omx_kinematics.py`의
   `object.__new__` + fake controller 패턴).
4. **`system_monitor`**: `_integrated_worker`를 어댑터로 축소 — 시퀀싱을
   `integrated_process.run_integrated_stages()` 순수 함수로 추출하고 세 클로저
   (`load_balls`/`await_verdict`/`sort_basket`)를 주입. `sorting_panel`은
   `omx2_sorting.sort_basket`에서 re-import. `OneCycleVisionRunner` 등 지역 구현
   삭제. 테스트: 전체 순서, 검사 타임아웃→부분 완료, 단계 간 취소, 실패 메시지,
   적재 생략 계획.

이후 서버 구현(각 소유 패키지)과 coordinator 노드는 TODO P1 항목대로 진행한다.

## 비고

- 검수 캠은 GUI `CameraFeed`가 계속 소유한다(통합 공정 중에도 해제하지 않음).
  따라서 `InspectBasket` 서버는 같은 장치를 열 수 없고, 자체 프레임 소스를
  갖거나 GUI 없는 환경에서만 구동해야 한다.
- 이 개발 머신에는 ROS2/colcon이 없다. 서버·노드 빌드와 launch 검증은 ROS2
  환경(Linux + colcon)에서 별도로 한다.
- 판정 규칙 단일 출처(`judge()` vs `from_counts()`) 문제는 TODO P1 참조 —
  `InspectBasket` 서버는 반드시 `count_detections()`/`judge()` 경로를 쓴다.
