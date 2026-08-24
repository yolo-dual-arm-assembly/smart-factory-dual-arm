# 리팩토링 백로그

시니어 개발자 관점에서 코드 품질·중복·테스트 갭을 감사한 결과다. `docs/TODO.md`가
기능·정책 부채(안전, 판정 기준, ROS2 서버 구현)를 다루는 것과 달리, 이 문서는
**리팩토링 성격의 부채**(중복, 긴 함수, 테스트 갭, 일관성)를 다룬다.

이 저장소는 패키지 하나에 브랜치 하나가 원칙이다(`AGENTS.md`). 그래서 항목마다
**담당 패키지**와 **범위**(패키지 로컬 = 그 브랜치에서 바로 처리 가능 / 공유 변경
필요 = `common` 등 보호 경로라 팀 합의 후 별도로 처리)를 표시해, 각 담당자가 자기
브랜치에서 이 문서의 자기 섹션만 가져가 처리할 수 있게 했다. 감사는 2026-08-24에
Explore 에이전트 3개로 코드베이스 전체를 병렬 조사해 작성했다.

## 우선순위 요약

가장 먼저 손대면 좋은 항목 5개 — 노력 대비 효과가 크고, 대부분 공유 변경이
필요 없다.

| 항목 | 담당 패키지 | 노력 | 왜 먼저인가 |
|---|---|---|---|
| `omx2_sorting` PASS/REJECT 러너 중복 제거 ([omx2_sorting #1](#1-packageroot--configdir--passreject-러너가-5개-파일에-중복)) | omx2_sorting | M | 79% 동일한 코드 2벌 + 5개 파일에 중복된 경로 상수. 최고 ROI |
| `common`에 `OMX2_CONFIG_DIR` 추가 ([common #1](#1-commonconstantspy에-omx2configdir-없음)) | common | S | 위 중복의 근본 원인. 작고 additive해서 합의 얻기 쉬움 |
| `omx2_sorting/README.md` 상태 갱신 ([omx2_sorting #2](#2-omx2sortingreadmemd가-완성된-코드를-미구현으로-문서화)) | omx2_sorting | S | 10분 작업, 완성된 코드를 미구현으로 오인하게 하는 혼란을 즉시 차단 |
| `RobotState` enum 사용, raw 문자열 제거 ([omx2_sorting #6](#6-손으로-쓴-passreject-문자열-robotstate-enum-미사용)) / `common.camera.open_camera()` 사용 ([omx1_loading #4](#4-pick_ballpyrun_vision_pickpy가-commoncameraopen_camera를-우회)) | omx2_sorting, omx1_loading | S 각각 | 둘 다 공유 합의 불필요, 실제 동작 차이를 만드는 잠재적 버그 제거 |
| `webcam.py`/`camera_feed.py` 캡처 엔진 통합 ([system_monitor #1](#1-webcampy-vs-camera_feedpy--캡처추론-엔진-중복)) | system_monitor | M | 문자 그대로 복붙된 코드(FPS 계산식 4곳 중복), 버그 수정이 한쪽에만 반영될 위험 |

---

## vision_inspection

### 세 가지 다른 CLI 에러 처리 스타일

- **위치:** `inspection_logic.py:231-281`(try/except 없음), `train.py:80-83`·`coco_import.py:319-322`(`ValueError`→`SystemExit`), `detect.py:79,88-89`(혼용)
- **문제:** `inspection_logic.py`의 `main()`은 예외 처리가 아예 없어 `RuntimeError`가 사용자에게 raw traceback으로 노출된다.
- **개선 방향:** `train.py`/`coco_import.py`의 `ValueError → SystemExit(str(error))` 패턴으로 패키지 전체 통일.
- **노력:** S · **범위:** 패키지 로컬

### `inspection_logic.py::main()`이 `parse_args()` 분리 패턴을 안 씀

- **위치:** `inspection_logic.py:232-262`
- **문제:** `train.py`·`coco_import.py`·`detect.py`는 각각 독립된 `parse_args() -> argparse.Namespace`를 뽑아내는데, 여기만 `main()` 안에 인라인으로 파서를 만든다.
- **개선 방향:** `parse_args()` 추출 — 다른 세 모듈과 일관성, 인자 파싱을 독립적으로 테스트 가능해짐.
- **노력:** S · **범위:** 패키지 로컬

### (참고) `docs/TODO.md`에 이미 등록된 항목

아래 두 개는 새로 발견한 게 아니라 `docs/TODO.md`에 이미 P1로 등록돼 있고, 이번
감사로 **여전히 유효함을 재확인**했다. 자세한 내용은 이 문서 뒤쪽 [TODO.md 검증
결과](#docstodomd-항목-검증-결과)를 참고.

- `normal_count = total_count - defect_count`가 무방비라 이물질만 있으면 음수가 됨 (`common/messages.py:32-38`, `inspection_logic.py:111-127`)
- `judge()`와 `from_counts()`가 분리돼 있는데 문서는 여전히 `from_counts()`를 PASS/REJECT 단일 출처로 안내 중

### 이미 잘 되어 있는 것

`inspection_logic.py`는 순수 함수·데이터클래스로 구성돼 있고 12개 모듈 중 9개가
직접 테스트돼 있다(나머지 3개는 rclpy/CLI 얇은 래퍼). `system_monitor/ui`가
본받아야 할 목표 패턴이다.

---

## system_monitor (GUI)

### 1. webcam.py vs camera_feed.py — 캡처+추론 엔진 중복

- **위치:** `webcam.py:127-214`(`_capture_worker`, `_inference_worker`), `camera_feed.py:252-358`(동일 역할)
- **문제:** 독립적인 두 개의 ~150줄짜리 이중 스레드 엔진이 거의 같은 일을 한다. FPS 지수이동평균 공식이 4곳(`webcam.py:147,195`, `camera_feed.py:282,355`)에 문자 그대로 복사돼 있고, 어노테이션+카운트 코드도 동일(`webcam.py:157-158`, `camera_feed.py:294-295`).
- **개선 방향:** `WebcamWindow`를 `CameraFeed`(이미 `snapshot()`/`take_preview()` 제공)를 내부에서 조합하는 얇은 `tk.Toplevel`로 만들거나, 캡처/추론 스레드를 공유 클래스로 추출.
- **노력:** M · **범위:** 패키지 로컬

### 2. 통합공정 오케스트레이션이 GUI 클래스에 파묻혀 테스트 불가

- **위치:** `viewer.py:414-490`(`start_integrated_process`, 77줄), `viewer.py:513-593`(`_integrated_worker`, 81줄), `viewer.py:595-629`(`_run_loading_once`, 35줄 — 메서드 안에 클래스를 중첩 정의)
- **문제:** 실제 픽업→검사→분류 오케스트레이션 로직이 `OperatorDashboard(tk.Tk)` 안에 있어 디스플레이 없이는 인스턴스화도 테스트도 불가능하다. 같은 파일의 `integrated_process.py::build_process_plan`은 의도적으로 GUI/장비 없이 만들어져 실제로 테스트되는데(`test_integrated_process.py`), 실행 로직 쪽은 같은 처리를 못 받았다.
- **개선 방향:** "사이클 1회 실행" 시퀀싱을 `build_process_plan`과 같은 패턴으로 순수 함수/클래스로 추출.
- **노력:** M · **범위:** 패키지 로컬

### 3. `webcam.py` 미사용 import

- **위치:** `webcam.py:29,32`
- **문제:** `common.camera`의 `_linux_camera_indexes`, `preferred_camera_indexes`를 import하지만 파일 어디서도 안 쓴다. `common/camera.py`는 "옛날 코드가 import해서" 유지한다는 주석까지 있는데, 그 "옛날 코드"가 여기 하나뿐이다.
- **개선 방향:** 미사용 import 2개 삭제.
- **노력:** XS · **범위:** 패키지 로컬

### 4. 죽은 클래스 `ArmMonitorGroup`

- **위치:** `arm_monitor.py:237-256`
- **문제:** `start_all`/`stop_all`/`snapshots`를 제공하지만 저장소 전체에서 호출하는 곳이 없다. `viewer.py`는 같은 목적으로 그냥 `dict[str, ArmMonitor]`를 쓴다.
- **개선 방향:** 삭제하거나, 원래 dict를 대체할 의도였다면 교체 후 dict 쪽 삭제.
- **노력:** XS · **범위:** 패키지 로컬

### 5. 죽은 매개변수 `OmxPanel.request_close(on_ready)`

- **위치:** `omx_panel.py:149-164`, 호출부 `viewer.py:1037-1039`
- **문제:** `on_ready` 콜백을 받아 바로 `del on_ready`(자체 주석으로 죽은 코드임을 인정). 호출부는 `self._finish_close`를 넘기고 바로 뒤에서 무조건 다시 호출한다.
- **개선 방향:** 매개변수 제거, 호출부 정리.
- **노력:** XS · **범위:** 패키지 로컬

### 6. `omx_manual_control.py::_build_ui`가 134줄짜리 모놀리스

- **위치:** `omx_manual_control.py:82-215`
- **문제:** 두 패키지(vision_inspection, system_monitor) 통틀어 가장 긴 UI 빌더 함수. 연결 프레임·관절 슬라이더 5개·그리퍼·명령 버튼을 한 함수에서 다 만든다. `viewer.py`/`dev_console.py`는 이미 `_build_status_row`/`_build_sidebar` 식으로 쪼개는 패턴을 쓴다.
- **개선 방향:** `_build_connection_frame`/`_build_joint_frame`/`_build_gripper_frame`/`_build_command_frame`으로 기계적 분리.
- **노력:** S · **범위:** 패키지 로컬

### 7. 독립 실행 GUI 스크립트의 sys.path 부트스트랩 방식이 두 가지

- **위치:** `dev_console.py:34-39`(공유 `common.bootstrap.ensure_workspace_path()` 사용) vs `omx_manual_control.py:21-25`(직접 손으로 좁게 구현, `vision_inspection`/`omx1_loading` 등은 등록 안 함)
- **문제:** `omx_manual_control.py`가 이미 있는 중앙 로직을 중복하면서 더 좁게 동작한다.
- **개선 방향:** `omx_manual_control.py`도 `ensure_workspace_path()`를 쓰도록 변경.
- **노력:** S · **범위:** 패키지 로컬

### 8. "지연 import + 모든 예외 삼킴" 패턴이 3번 반복

- **위치:** `viewer.py:172-177`(`_configured_target_count`), `viewer.py:999-1010`(`_verdict_reason`), `camera_feed.py:360-394`(`_inspection_from`)
- **문제:** `try: from vision_inspection.X import Y ... except Exception: <폴백>` 모양이 독립적으로 3번 등장, 폴백 동작도 각자 다르게 결정돼 있다.
- **개선 방향:** `system_monitor/ui/vision_bridge.py` 같은 작은 헬퍼 모듈로 방어적 호출 계약을 한 곳에서만 책임지게 함.
- **노력:** S-M · **범위:** 패키지 로컬

### 9. GUI가 raw `YOLO(...)`를 재구현 (cross-package, 소비 측만)

- **위치:** `webcam.py:177`, `camera_feed.py:319`, `dev_console.py:584`
- **문제:** 세 곳 다 직접 `YOLO(str(model_path))`를 호출한다. `vision_inspection/inspection_logic.py:139-148`에 이미 `@lru_cache` 캐싱 + `warn_on_mismatch()`(모델 클래스명 검증)가 딸린 `load_model()`이 있는데 그 혜택을 못 받는다.
- **개선 방향:** 세 호출 지점을 `vision_inspection.inspection_logic.load_model(path)`로 교체. vision_inspection 쪽 변경은 필요 없음(소비자만 바꾸면 됨).
- **노력:** S · **범위:** 패키지 로컬(system_monitor에서 import만 바꿈)

### 10. 하드코딩된 `"best.pt"`가 `vision_inspection.models`와 중복 (cross-package, 조율 필요)

- **위치:** `viewer.py:90`(`INSPECTION_MODEL_PATH = MODELS_DIR / "best.pt"`) vs `vision_inspection/models.py`의 `MODEL_SPECS[0]`
- **문제:** `dev_console.py:363`는 올바르게 `SPECS_BY_LABEL[...].filename`으로 가져다 쓰는데 `viewer.py`만 문자열 리터럴을 직접 씀.
- **개선 방향:** `vision_inspection/models.py`에 `CUSTOM_MODEL_FILENAME = MODEL_SPECS[0].filename` 같은 이름 있는 export를 추가하고 `viewer.py`가 import. **양쪽 패키지를 다 건드리므로 vision_inspection 담당자와 조율 필요.**
- **노력:** S · **범위:** 공유 변경 필요(작음)

### 11. GUI 검사 실패 상태가 조용히 사라짐 (`docs/TODO.md` 항목 8, 재확인됨)

- **위치:** `camera_feed.py:393-394`(`except Exception: return None, False`), `camera_feed.py:302-313` vs `318-328`
- **문제:** 모든 검사 변환 예외가 로그 없이 `None`이 된다. 캡처 스레드는 추론 스레드의 모델 로드 실패와 무관하게 매 프레임 `connected=True` 스냅샷을 무조건 덮어써서, 모델이 로드 실패한 상태에서도 GUI는 "연결됨"으로 계속 보인다.
- **개선 방향:** 레이트 제한 로깅 추가 + 카메라-연결 상태와 별개인 명시적 GUI 에러 상태 필드 추가; 모델/추론 실패는 캡처 스레드가 덮어쓰지 못하는 필드에 래치.
- **노력:** M · **범위:** 패키지 로컬

### 12. 테스트 갭이 여기 집중됨

- **위치:** 15개 모듈 중 실질 커버리지는 `integrated_process.py`, `ui_fonts.py`뿐.
- **문제:** `tests/test_webcam.py`는 이름과 달리 실제로 `common.camera.linux_camera_indexes`를 테스트하고 `system_monitor.ui.webcam`은 아예 import도 안 한다 — `WebcamWindow`(순수 함수 `_scale_for_preview` 포함)는 커버리지 0. `device_roles.py`는 스스로 "하드웨어 없이 시험 가능"이라고 문서화까지 해놨는데 테스트가 없다.
- **개선 방향:** `tests/test_webcam.py`를 `tests/test_camera_indexes.py`로 개명하고 `webcam.py`용 새 테스트 작성. `tests/test_device_roles.py` 신규 작성(`assign_omx_ports`, `assign_camera_roles`, `is_non_robot_port` 등 순수 함수).
- **노력:** 모듈당 S · **범위:** 패키지 로컬

### 낮은 우선순위(vision_inspection)

- `detect.py:75-142` `main()` 68줄 — 의도적으로 단순한 데모 스크립트라 분리 실익 적음
- `colab.py:129-184` `extract_dataset` 56줄 — 길지만 응집도 높고 변경 빈도 낮음
- `stability.py:84-123` `VerdictStabilizer.update` 40줄 — 경계선이지만 정당하게 밀도 높은 상태기계, 테스트도 있어 리팩토링 대상으로 부적합
- `vision_node.py`의 `pick_best`와 `inspection_logic.py`의 `count_detections`/`detected_class_names` — 둘 다 `result.boxes`를 순회하지만 실제로 다른 걸 계산함, 표면적 유사성일 뿐 진짜 중복 아님

---

## omx1_loading

### 1. 휠/colcon 설치 시 config 리소스를 못 찾음

- **위치:** `omx1_loading/setup.py:9-12`
- **문제:** `data_files`가 ament 리소스 인덱스와 `package.xml`만 나열하고 `config/`는 안 넣는다. `docs/TODO.md` 항목 12는 이 버그를 `vision_inspection`/`omx2_sorting`/`system_monitor`만 담당자로 지목하는데 **omx1_loading도 동일한 버그가 있다** — 진짜(non-editable) colcon 빌드/휠 설치는 `omx1_loading/config/*.json`을 안 딸고 간다.
- **개선 방향:** `config/*.json`을 `share/omx1_loading/config`로 설치하고, `OMX1_CONFIG_DIR` 해석이 설치된 share 경로를 우선하되 소스 트리로 폴백하게 변경.
- **노력:** M · **범위:** 패키지 로컬

### 2. `loading_node.py`의 팔 명령은 로그 전용 자리표시자

- **위치:** `loading_node.py:75-87`(`command_move`, `command_home`, `command_stop`)
- **문제:** 셋 다 `self.get_logger().info/warning(...)`만 호출한다. `on_detection`/`check_watchdog`의 디바운스·워치독 상태기계는 실제로 동작하지만, `common.omx_controller.OmxController`를 실제로 구동하는 코드가 없다. 파일 docstring이 의도적 스캐폴딩임을 밝히고 있어 긴급도는 낮음.
- **개선 방향:** `OmxController`를 주입하고 세 자리표시자를 `pick_ball.py` 패턴을 따라 실제 `move_xyz`/`home`/`request_stop` 호출로 교체.
- **노력:** M · **범위:** 패키지 로컬

### 3. 관심사가 섞인 긴 함수들

| 위치 | 함수 | 줄 수 | 문제 |
|---|---|---|---|
| `pick_ball.py:202-294` | `OmxVisionRunner.run()` | 93 | 카메라 캡처+YOLO 디바운스+안전구역 체크+다단계 모션+오버레이 그리기+키보드 처리가 한 루프에 |
| `teaching_window.py:244-329` | `_camera_worker()` | 86 | 캡처 루프+YOLO 추론+컨벡스헐/마커 그리기+잠금상태 처리 |
| `imitation_control.py:57-130` | `OmxTaughtVisionRunner.run()` | 74 | `pick_ball.run()`과 동일한 혼합 |
| `teaching_window.py:106-242` | `_build_ui()` | 137 | (낮은 심각도 — 대체로 선언적) |
| `pick_ball.py:331-388` | `_execute_action()` | 58 | (낮은 심각도) |

- **참고:** 처음엔 `loading_node.py`의 콜백들도 의심했지만 실제로는 짧고 단일 목적임(`on_detection` ~20줄, `check_watchdog` ~10줄) — 확인 결과 문제 없음.
- **개선 방향:** 파일별로 캡처/탐지/그리기/동작을 메서드로 기계적 분리. 장기적으로는 아래 4번 항목의 공유 베이스 클래스로 흡수.
- **노력:** 파일당 M, 누적 L · **범위:** 패키지 로컬

### 4. 구조적 중복: `OmxVisionRunner` vs `OmxTaughtVisionRunner`

- **위치:** `pick_ball.py:145-419`(`OmxVisionRunner`) vs `imitation_control.py:19-215`(`OmxTaughtVisionRunner`)
- **문제:** 복붙은 아니지만(메서드/변수명이 다름) 처음부터 끝까지 같은 모양이 중복된다: `deque` 기반 픽셀 스무딩, `hit_frames`/`miss_frames` 디바운스 카운터, `_stop_event`/`_home_event` 스레딩 패턴, `connect→home→loop→finally` 생명주기, `request_stop()`/`request_home()` 공개 API, 거의 동일한 `_draw_*` 오버레이 헬퍼. 한쪽에서 고친 버그(예: 안전구역 체크)가 다른 쪽엔 전파되지 않는다.
- **개선 방향:** 캡처/디바운스/스레딩/정리를 소유하는 공유 `VisionRunnerBase`(또는 조합 가능한 `DetectionLoop` 헬퍼) 추출. `_execute_action`/`_move_to_taught_pose`만 서브클래스별 오버라이드로 남김.
- **노력:** L · **범위:** 패키지 로컬

### 5. `pick_ball.py`/`run_vision_pick.py`가 `common.camera.open_camera()`를 우회

- **위치:** `pick_ball.py:207`, `run_vision_pick.py:81`(직접 `cv2.VideoCapture(...)`)
- **문제:** `common/camera.py`는 정확히 일관된 백엔드 선택(윈도우 DSHOW 폴백)·해상도/FourCC/버퍼 설정·명확한 `RuntimeError`를 위해 존재하고, `teaching_window.py`/`imitation_control.py`/`camera_calibration.py`는 이미 올바르게 사용 중이다. 이 두 곳만 건너뛰어서 같은 카메라라도 픽업 경로와 교시/모방 경로에서 동작이 다르다.
- **개선 방향:** 두 호출부를 `common.camera.open_camera(index)`로 교체.
- **노력:** S · **범위:** 패키지 로컬

### 6. 카메라↔로봇 포인트 수집 캘리브레이션의 독립된 두 구현

- **위치:** `camera_calibration.py:21-249`(Tkinter GUI) vs `run_vision_pick.py:60-141`(`cmd_calibrate`, raw cv2 창 + 터미널 입력)
- **문제:** 둘 다 4개 이상의 픽셀/로봇-XY 대응점을 모아 `OmxCalibration.compute()`/`save()`를 호출하지만 완전히 별도로 유지되는 두 UX 흐름이다. 검증 로직이 바뀌면 두 번 손봐야 한다.
- **개선 방향:** 포인트 수집/검증 루프를 `coordinate_transform.py`의 작은 공유 헬퍼로 추출하고 렌더링/입력 처리만 분리 유지.
- **노력:** M · **범위:** 패키지 로컬

### 7. `common.logger` 미사용, 조용한 `except Exception: pass`

- **위치:** `teaching_window.py:401,582`(완전히 조용한 `except Exception: pass`, 로그조차 없음)
- **문제:** `common/logger.py`가 정확히 이런 상황을 막으려고 존재하는데(자체 docstring이 명시) omx1_loading 파일 중 아무도 안 쓴다. `print()` 사용: `run_vision_pick.py` 23회, `pick_ball.py` 7회, `imitation_control.py` 5회, `coordinate_transform.py` 3회.
- **개선 방향:** "라이브러리" 모듈(`pick_ball.py`, `imitation_control.py`, `coordinate_transform.py`)은 `logger.info/warning/error()`로 교체. 조용한 `pass` 두 곳은 최소한 삼키기 전에 로그. 대화형 CLI 프롬프트(`run_vision_pick.py`)는 print 유지해도 무방.
- **노력:** 파일당 S, 누적 M · **범위:** 패키지 로컬

### 8. 테스트 커버리지 갭

- **위치:** `teaching_window.py`(587줄), `camera_calibration.py`(248줄), `imitation_control.py`의 `OmxTaughtVisionRunner`(214줄), `loading_node.py`(103줄), `run_vision_pick.py`/`run_imitation.py` — `tests/`에서 참조 0건.
- **문제:** 3·4번 항목의 긴 함수/중복 로직이 지금은 실하드웨어 실행으로만 검증 가능하다. 순수 로직 부분(`is_safe_approach_target`, `validate_pick_place_plan`, `OmxTeachingDataset.predict`)은 이미 `test_omx_kinematics.py`/`test_omx_teaching.py`에 잘 테스트돼 있음 — 갭은 구체적으로 상태를 가진 러너/GUI/CLI 껍데기 쪽.
- **개선 방향:** 4번 항목이 상태기계를 순수 클래스로 분리하면, `test_omx_waypoints.py`의 `RecordingController` 패턴처럼 주입 가능한 페이크로 테스트 추가.
- **노력:** L · **범위:** 패키지 로컬

---

## omx2_sorting

### 1. `PACKAGE_ROOT`/`CONFIG_DIR` + PASS/REJECT 러너가 5개 파일에 중복

- **위치:** `pass_motion.py:20-21,25-147`, `reject_motion.py:17-18,22-138`, `test_motion.py:10-12,15-124`, `test_motion_reject.py:9-11,14-104`, `teach_motion.py:8-9`
- **문제:** `PACKAGE_ROOT = Path(__file__).resolve().parent.parent; CONFIG_DIR = PACKAGE_ROOT / "config"`가 5개 파일에 그대로 재입력돼 있다. `pass_motion.run()`/`reject_motion.run()`은 **79% 줄이 동일**(difflib 검증, 147줄 중 113줄 일치 — PASS↔REJECT 문자열과 `inspection.is_pass` 방향만 다름). `test_motion.py`/`test_motion_reject.py`는 같은 루프를 더 허술하게 복사한 것(56% 일치)인데 `InspectionResult` 게이트를 아예 건너뛴다.
- **개선 방향:** `omx2_sorting/motion_runner.py`에 `run_motion(controller, inspection, *, expect_pass, path) -> RobotStatus`를 만들고 `pass_motion.py`/`reject_motion.py`를 10줄짜리 래퍼로 축소. `test_motion.py`/`test_motion_reject.py`는 삭제하고 단일 `--motion pass|reject` 드라이런 CLI로 대체(파일명도 `test_*`라 pytest collection과 헷갈리므로 개명 필요).
- **노력:** M · **범위:** 패키지 로컬(단, `PACKAGE_ROOT`/`CONFIG_DIR` 중복의 근본 원인은 아래 [common #1](#1-commonconstantspy에-omx2configdir-없음))

### 2. `omx2_sorting/README.md`가 완성된 코드를 미구현으로 문서화

- **위치:** `omx2_sorting/README.md` 상태 표
- **문제:** `pass_motion.py`/`reject_motion.py`를 "구현 필요"로 표시하지만 둘 다 검증·토크 제어·안전 종료 처리가 딸린 완성된 117-123줄짜리 함수다. 진짜 스텁은 `move_basket.py`(아래 3번)뿐인데 README가 구분을 안 한다.
- **개선 방향:** 상태 열을 실제 상태(`move_to_inspection()`만 미구현)에 맞게 갱신.
- **노력:** S · **범위:** 패키지 로컬

### 3. `move_basket.move_to_inspection()`은 진짜 스캐폴드

- **위치:** `move_basket.py:14-25`
- **문제:** `raise NotImplementedError(...)` — "구현 필요" 라벨에 정확히 해당하는 유일한 함수. (`open_controller`는 사소해서 문제 없음.)
- **개선 방향:** 1번 항목의 공유 러너가 생기면 같은 웨이포인트-JSON 패턴으로 구현.
- **노력:** M(실제 모션 설계 필요) · **범위:** 패키지 로컬

### 4. `teach_motion.py::main()`이 199줄

- **위치:** `teach_motion.py:54-252`
- **문제:** 범위 내 최대 단일 함수. CLI 메뉴 루프+하드웨어 토크/읽기 호출+JSON 저장이 전부 인라인.
- **개선 방향:** 메뉴 처리, 하드웨어 읽기, JSON 저장을 별도 함수로 분리.
- **노력:** M · **범위:** 패키지 로컬

### 5. 손으로 쓴 `"PASS"`/`"REJECT"` 문자열, `RobotState` enum 미사용

- **위치:** `waypoints.py:47`(`load_waypoint_plan(path, *, expected_motion: str)` — `str` 타입), 호출부 `pass_motion.py:56`, `reject_motion.py:53`, `test_motion.py:29`, `test_motion_reject.py:24`, `teach_motion.py:22,25`
- **문제:** `common.constants.RobotState.PASS`/`.REJECT`가 이미 정확히 이 문자열 값으로 존재하고 반환 상태값으로는 이미 import돼 쓰이는데, 웨이포인트 JSON의 `"motion"` 필드는 그냥 문자열로 검증돼서 오타(`"Pass"`, 끝 공백)가 런타임 JSON 로드 시점에야 실패한다.
- **개선 방향:** `WaypointPlan.motion`/`load_waypoint_plan(expected_motion=...)`이 `RobotState`를 받게 변경. `common`은 이미 `RobotState`를 갖고 있어 공유 변경 불필요.
- **노력:** S · **범위:** 패키지 로컬

### 6. 광범위한 `except Exception`이 복구 가능한 오류와 프로그래밍 오류를 구분 안 함

- **위치:** `pass_motion.py:139`, `reject_motion.py:130`, `test_motion.py:115`, `test_motion_reject.py:98`, `teach_motion.py:244` — 전부 catch-and-print
- **문제:** 하드웨어 오류와 버그를 같은 방식으로 처리해 원인 구분이 안 된다.
- **개선 방향:** `(OmxCommunicationError, OmxCancelled, OSError)`로 좁힘.
- **노력:** S · **범위:** 패키지 로컬

### 7. `common.logger` 미사용

- **위치:** `teach_motion.py`(51회 print), `test_motion.py`(16회), `pass_motion.py`/`reject_motion.py`(각 7회) — omx2_sorting 전체 93회 print, `common.logger` 0회(가장 많이 쓰면서 가장 안 쓰는 패키지)
- **개선 방향:** 라이브러리 모듈은 logger로, 대화형 CLI는 print 유지.
- **노력:** 파일당 S, 누적 M · **범위:** 패키지 로컬

### 8. 테스트 커버리지 갭

- **위치:** `move_basket.py`, `teach_motion.py`(252줄) — `tests/`에서 참조 0건. `reject_motion.run()`은 테스트 호출 **0건**, `pass_motion.run()`은 실패-폐쇄 케이스 1건만(성공 경로 테스트 없음).
- **개선 방향:** 1번 항목으로 공유 러너를 뽑아낸 뒤 `RecordingController` 페이크로 성공/실패 양쪽 경로 테스트 추가, `reject_motion.run()`도 대칭으로.
- **노력:** L · **범위:** 패키지 로컬

---

## system_coordinator

### `system_coordinator`와 `omx2_sorting`은 진짜 ROS2 패키지가 아님

- **위치:** `ros2_ws/src/system_coordinator/`, `ros2_ws/src/omx2_sorting/` — 둘 다 `package.xml`/`setup.py`/`setup.cfg` 없음(`omx1_loading`·`common`은 셋 다 있음)
- **문제:** `docs/TODO.md` 항목 7("ROS2 서비스·액션 서버와 coordinator 노드 구현")이 이미 이 부재를 지목하지만, **system_coordinator 자체도 똑같이 colcon으로 빌드 불가능**하다는 세부사항까지는 명시하지 않는다 — `coordinator_node.py`가 아예 없고, `communication.py`의 `LocalChannel`은 자체 docstring에서 미래 ROS2/소켓 구현으로 교체될 같은-프로세스 임시 대역이라고 밝힘. `MainController`/`StateMachine`은 순수하고 잘 테스트돼 있지만 실제 ROS2 토픽/서비스/액션으로 다른 패키지와 연결하는 코드가 없다. 실제로 `system_monitor/ui/viewer.py`의 `_integrated_worker()`가 테스트된 `MainController`를 쓰지 않고 같은 시퀀싱을 자체적으로 중복 구현하고 있다.
- **개선 방향:** `docs/ros2_migration.md`에 이미 계획된 4단계 진입점 추출을 따라 `system_coordinator`·`omx2_sorting`에 `package.xml`/`setup.py`를 추가하고, 얇은 `coordinator_node.py`와 `SortBasket`/`LoadBalls`/`InspectBasket` 서버 래퍼를 기존 순수 함수 위에 씌운다. `project_interfaces`(이미 정의됨)가 공유 계약이라 추가 `common` 변경은 불필요.
- **노력:** L · **범위:** 패키지 로컬(통합 담당은 system_coordinator, omx1_loading/omx2_sorting은 각자 액션 서버 제공)
- **참고:** 이미 `docs/TODO.md` P1에 추적 중 — 이 항목은 신규 발견이라기보단 system_coordinator 쪽 세부사항을 보강한 확인.

### 규칙 준수 확인(문제 아님)

- 패키지 간 불법 import 없음 — `omx1_loading`/`omx2_sorting`/`system_coordinator` 상호 검색 결과 0건. `main_controller.py`는 노드 패키지를 직접 import하지 않고 의존성 주입 콜백을 씀.
- `common.messages` 데이터클래스가 확인한 모든 경계에서 올바르게 사용됨(raw dict 없음).
- `system_coordinator/state_machine.py`는 이미 `ALLOWED_TRANSITIONS: dict[RobotState, tuple[RobotState, ...]]` 형태의 enum 기반 테이블이고 완전히 테스트돼 있음 — 손댈 필요 없음.
- `communication.py`의 `LocalChannel`은 의도적이고 문서화되고 테스트된 스텁(`test_main_controller.py`가 pub/sub 순서까지 검증) — 진짜 갭은 위에서 언급한 "교체해 넣을 ROS2 노드 자체가 없다"는 것.
- `common/omx_controller.py`는 어디서도 재구현되지 않음.

---

## common — 공유, 팀 합의 필요

### 1. `common/constants.py`에 `OMX2_CONFIG_DIR`이 없음

- **위치:** `common/constants.py:53`(`OMX1_CONFIG_DIR`은 있음, 대응하는 OMX2용 상수 없음)
- **문제:** 모듈 자체 docstring은 경로 상수가 딱 한 곳에만 있어야 한다고 말하는데, import할 공유 상수가 없어서 `omx2_sorting`의 5개 파일이 로컬로 재계산한다 — [omx2_sorting #1](#1-packageroot--configdir--passreject-러너가-5개-파일에-중복)의 근본 원인.
- **개선 방향:** `OMX1_CONFIG_DIR` 패턴을 그대로 따라 `OMX2_CONFIG_DIR`, `OMX2_PASS_WAYPOINTS_PATH`, `OMX2_REJECT_WAYPOINTS_PATH` 추가.
- **노력:** S(additive, non-breaking) · **범위:** 공유 변경 필요 — 다만 작고 위험도 낮아 합의를 얻기 쉬운 후보.

### 2. 순수 로직인데 테스트가 없는 두 곳

- **위치:** `common/constants.py:25-39` `find_project_dir()`
- **문제:** `models/`, `object/`, `result/`, 모든 config 파일 위치를 결정하는 순수 경로 해석 로직(환경변수 우선 → 마커 탐색 → cwd 폴백)인데 직접 테스트가 0건이다. `main.py`/`bootstrap.py` 주석에서 "colcon 설치 vs 소스 트리 실행 간 취약함"으로 스스로 지목하는 함수다.
- **개선 방향:** 환경변수 override, 마커 탐색 성공/실패, cwd 폴백 각각에 대한 테스트 추가.
- **노력:** S · **범위:** 공유 변경 필요(테스트 추가라 위험도 낮음)

---

## 저장소 전반 — 팀 합의 필요

### 로깅 일관성

`common/logger.py`는 정확히 "담당자마다 print를 다르게 쓰는 문제"를 막으려고
만들어졌는데(자체 docstring), 실제 로직이 있는 6개 패키지 중 2개(system_coordinator,
vision_inspection)에서만 채택됐다.

| 패키지 | `print()` | `common.logger` | rclpy `get_logger()` |
|---|---|---|---|
| common | 11 | 0(정의부) | 0 |
| omx1_loading | 38 | 0 | 4 |
| omx2_sorting | 93 | 0 | 0 |
| system_coordinator | 1 | 5 | 0 |
| system_monitor | 37 | 0 | 0 |
| vision_inspection | 16 | 7 | 2 |
| **합계** | **196** | **12** | **6** |

**개선 방향:** 팀 결정 필요 — CLI/수동 스크립트는 print를 유지해도 되는지, 라이브러리/노드 코드는 어디까지 logger로 이전할지 범위 합의. 합의되면 각 패키지가 자기 브랜치에서 처리(공유 인프라는 이미 있으므로 `common` 변경은 불필요).

### 설정 로딩 패턴 3종 난립

`common`에 공유 설정 로딩 헬퍼가 없어서 같은 "구조화 파일 읽기→검증→데이터클래스"
작업을 3가지 독립 방식으로 각자 구현했다:

1. `vision_inspection/class_scheme.py:126-128` — yaml, 자체 `_read_config()`로 예외 처리
2. `omx1_loading/teaching.py:143`, `coordinate_transform.py:186` — json, 두 파일에 독립 중복
3. `omx2_sorting/waypoints.py:57-62` — json + `JSONDecodeError → ValueError` 변환; `system_monitor/ui/sorting_teach_window.py:313`가 `waypoints.load_waypoint_plan()`을 재사용하는 대신 같은 모양을 또 재구현

**개선 방향:** `AGENTS.md`가 "편의를 위해서만" `common`으로 옮기는 걸 명시적으로 만류하므로, 통합할지 그대로 둘지는 팀 합의 사안. 최소한 `sorting_teach_window.py`가 기존 `waypoints.load_waypoint_plan()`을 재사용하도록 하는 것은 패키지 로컬로 가능(system_monitor).

### CI 부재

- **위치:** 저장소 전체에 `.github/workflows` 등 CI 설정 없음.
- **문제:** `docs/TODO.md` 항목 11이 이미 지목하고 있으나, "`.venv`에 pytest가 없어 미실행"이라는 반복된 완료 기록은 **이제 사실이 아니다** — `.venv`에 pytest 9.1.1이 설치돼 있음(확인함). 실제로 스위트를 돌려보고 완료 기록을 갱신해야 한다.
- **개선 방향:** `AGENTS.md`가 문서화한 로컬 명령(`compileall` + `pytest -q`) 그대로 기본 CI 워크플로 추가.
- **노력:** S-M · **범위:** 저장소 전반/팀 합의 필요

### 타입 주석 갭 (경미)

AST로 공개 API 전체를 스캔한 결과 15개 갭, 전부 `__init__` 생성자는 100%
주석됨. 갭은 `omx2_sorting`의 수동/개발 스크립트(`teach_motion.py`,
`test_motion*.py`)에 집중, `vision_node.py::pick_best`/`main`,
`camera_feed.py::take_preview`/`raw_frame` 등에 산발적으로 존재. 심각도 낮음,
해당 패키지 작업 시 같이 정리하면 충분.

### 깨끗한 영역 (문제 없음, 명시할 가치 있음)

- **경로 처리:** `os.path` 사용 0건 — `pathlib` 전면 사용, `AGENTS.md` 지침 완전 준수.
- **인코딩:** 모든 텍스트 I/O(`ros2_ws/src` 12곳, `tests/` 13곳)가 `encoding="utf-8"` 명시.
- **`pyrightconfig.json`/`pyproject.toml` 경로 목록:** 1:1 일치, 드리프트 없음.
- **`requirements.txt`/`pyproject.toml` 의존성:** 완전 일치, 드리프트 없음.
- **`main.py`의 수동 `sys.path` 삽입:** 문제 아님 — `bootstrap.ensure_workspace_path()` 자체가 `common` 안에 있어서 그 함수를 부르기 전에 `common`을 먼저 올려야 하는 구조적 이유가 있고, `AGENTS.md`가 명시적으로 설명함.

---

## docs/TODO.md 항목 검증 결과

`docs/TODO.md`의 14개 항목을 현재 코드와 대조해 재검증했다.

| # | 항목 | 표시 | 판정 | 근거 |
|---|---|---|---|---|
| 1 | 반복 공정 사이클 정상화 | [x] | **수정 확인됨** | `main_controller.py:94-108`의 `_prepare_cycle()`이 COMPLETE→IDLE 자동 리셋, ERROR 재진입 차단 |
| 2 | 로봇 이동 실패를 호출자에게 전파 | [x] | **수정 확인됨** | `omx_controller.py:565-591` `move_xyz()`가 `ik_5dof()` 예외를 삼키지 않음 |
| 3 | 모든 관절 명령에 소프트 리밋 적용 | [x] | **수정 확인됨** | `move_joints_smooth`/`move_joints` 모두 `validate_joint_angles()` 선행 호출 |
| 4 | 물리적 안전 인터록/비상정지 정책 | [ ] | **여전히 유효, 손 안 댐** | interlock/e_stop/emergency 검색 결과 0건 |
| 5 | 검사 결과에서 이물질 분리(foreign_count) | [ ] | **여전히 유효** | `normal_count = total_count - defect_count`가 무방비, `foreign_count`가 `defect_count`에 합쳐짐 → 이물질만 있으면 음수 |
| 6 | PASS/REJECT 단일 출처 확립 | [ ] | **여전히 유효(문서 리스크)** | `judge()`와 `from_counts()`가 분리, 문서가 여전히 `from_counts()`를 단일 출처로 잘못 안내 |
| 7 | ROS2 서비스·액션 서버·coordinator 노드 구현 | [ ] | **여전히 유효** | 서버 코드 전무, omx2_sorting/system_coordinator는 package.xml/setup.py조차 없음(위 system_coordinator 섹션 참고) |
| 8 | GUI 검사 실패 상태 보존/표시 | [ ] | **여전히 유효** | `camera_feed.py:393-394` 예외 삼킴, 캡처 스레드가 모델 로드 실패와 무관하게 연결 상태를 매 프레임 덮어씀(위 system_monitor #11) |
| 9 | ROS2 노드 실시간성/QoS 검증 | [ ] | 재검증 범위 밖(신규 기능/하드닝 영역) | — |
| 10 | 통합·ROS2·하드웨어 경계 테스트 | [ ] | **여전히 유효, 정확히 설명된 대로** | `reject_motion.run()`은 테스트에서 한 번도 호출 안 됨 |
| 11 | CI와 정적 검사 구성 | [ ] | **여전히 유효하나 전제 일부 낡음** | CI 없음. "pytest 미설치" 주장은 이제 거짓(9.1.1 설치돼 있음) — 완료 기록 갱신 필요 |
| 12 | 설치본에서 설정·웨이포인트 리소스 확인 | [ ] | **여전히 유효, 부분적으로만 뼈대** | vision_inspection은 data_files 선언(부분 진전), omx2_sorting은 setup.py 자체가 없음. **omx1_loading도 같은 버그 있음(위 omx1_loading #1)** — 담당자 목록에 빠져 있었음 |
| 13 | 문서와 구현 상태 동기화 | [ ] | **여전히 유효 — 재확인** | omx2_sorting/README.md가 완성된 코드를 미구현으로 표시(위 omx2_sorting #2). system_coordinator/README.md는 정확함 |
| 14 | 중복 코드와 광범위 except 정리 | [ ] | **여전히 유효, 완전히 재확인됨** | PACKAGE_ROOT/CONFIG_DIR 5개 파일 중복(위 omx2_sorting #1), except Exception 저장소 전체 58회 중 62%가 system_monitor |

---

## 테스트 커버리지 갭

하드웨어/GUI 없이 오늘 당장 테스트 가능한데 안 돼 있는 것 중 위험도가 가장 높은
3가지 (상세는 각 패키지 섹션 참고):

1. **`system_monitor/ui/device_roles.py`**(전체 파일, 테스트 0건) — 어느 물리적 로봇 팔에 어느 시리얼 포트를 배정할지 결정하는 순수 함수들. 자체 docstring이 "하드웨어 없이 시험 가능"이라고 명시했는데 한 번도 테스트된 적 없음. **잘못 배정되면 엉뚱한 팔에 명령이 나감.**
2. **`common/constants.py::find_project_dir()`** — 모든 데이터/config/모델 파일 위치를 결정하는 순수 경로 해석 로직, 직접 테스트 0건.
3. **`system_monitor/ui/webcam.py`** — 커버리지 0인데 `tests/test_webcam.py`라는 이름이 오해를 줌(실제로는 `common.camera.linux_camera_indexes`를 테스트).

패키지별 전체 커버리지 갭은 각 패키지 섹션의 "테스트 커버리지 갭" 항목 참고.

---

## Git 브랜치 상태

7개 패키지, 7개 원격 브랜치(HEAD 제외) — 매핑이 깔끔하지 않다.

| 브랜치 | 마지막 커밋 | 대응 패키지 | dev 병합 여부 | 권고 |
|---|---|---|---|---|
| `origin/feat/GUI` | 2026-08-11(13일 정체) | system_monitor | 예, 고유 커밋 0개 | 삭제 안전 |
| `origin/feat/yolo` | 2026-08-21(3일) | vision_inspection | 예, 고유 커밋 0개(조사 시점) | 이 세션이 사용 중인 브랜치 — 최신 커밋이 실제로 dev에 병합됐는지 삭제 전 재확인 |
| `origin/feat/omx2-sorting` | 2026-08-05(19일 정체) | omx2_sorting | 예, 고유 커밋 0개 | 삭제 안전 |
| `origin/feat/omx1` | 2026-08-05(19일 정체) | omx1_loading | 아니오(형식상) | "고유" 커밋 2개가 전부 병합 커밋 — 실질적으로 죽은 브랜치, 대체됐는지 확인 후 삭제 |
| `origin/feat/omx1-rule-based` | 2026-08-21(3일) | omx1_loading | 아니오 | **진짜 미병합 커밋 1개**(`"FEAT: can pick&drop but need more fix"`) — 진행 중인 작업, 유지 |
| (브랜치 없음) | — | common, project_interfaces, system_coordinator | — | 전용 브랜치 자체가 없었음 — dev에서 직접 편집하는 보호 경로 모델과 일치. 공식 컨벤션으로 문서화할지만 팀이 결정 |

**참고:** `omx1_loading`이 브랜치 2개를 갖게 된 경위(`feat/omx1`이 `feat/omx1-rule-based`로
대체된 것인지)는 git 상태만으로는 알 수 없어 담당자 확인이 필요하다.
