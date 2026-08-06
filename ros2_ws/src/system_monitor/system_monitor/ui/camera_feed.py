"""카메라 한 대를 읽고, 필요하면 YOLO 추론까지 붙이는 백그라운드 피드.

구조는 :mod:`system_monitor.ui.webcam`에서 검증된 방식을 그대로 쓴다. 영상
프레임레이트가 추론 속도에 묶이지 않도록 스레드를 둘로 나눈다.

- 캡처 스레드: 카메라 속도로 프레임을 읽고 마지막 추론 결과를 합성한다.
- 추론 스레드: 최신 원본 프레임만 골라 추론하고 결과를 남긴다(밀린 프레임은 건너뜀).

카메라도 배타 자원이라 피드가 장치를 쥔 채로는 교시 창이나 비전 실행기가 같은
카메라를 열지 못한다. 그래서 :meth:`release` / :meth:`acquire`로 인계한다.

Tk는 스레드 안전하지 않으므로 이 클래스는 위젯을 만지지 않는다. 최신 화면은
:meth:`snapshot`으로 꺼내 가고, 갱신은 메인 스레드의 ``after`` 폴링이 맡는다.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path

from common.camera import open_camera
from common.messages import InspectionResult

# common.camera의 기본 캡처 크기와 같은 값을 쓴다. open_camera가 MJPG로 열기
# 때문에 압축된 프레임이 흘러 USB 대역폭 부담이 크지 않다.
# 카메라가 이 크기를 지원하지 않으면 드라이버가 가까운 값을 주며, 화면에는
# 실제로 받은 프레임 비율이 그대로 나간다(VideoPanel이 비율을 유지해 맞춘다).
#
# 캠 두 대를 같은 USB 컨트롤러에 물려 프레임이 끊기면 이 두 값을 640x480으로
# 낮춘다. 화면 비율과 배치는 실제 프레임을 따라가므로 그대로 동작한다.
FEED_WIDTH = 1280
FEED_HEIGHT = 720
INFERENCE_CONFIDENCE = 0.5
# 새 프레임이 없을 때 추론 스레드가 CPU를 태우지 않도록 잠깐 쉰다.
IDLE_SLEEP_SEC = 0.005
RETRY_INTERVAL_SEC = 2.0


@dataclass(frozen=True)
class CameraSnapshot:
    """어느 시점의 카메라 상태. 화면에 그대로 뿌릴 수 있는 형태다."""

    connected: bool = False
    index: int | None = None
    name: str = ""
    video_fps: float = 0.0
    infer_fps: float = 0.0
    detection_count: int = 0
    inspection: InspectionResult | None = None
    message: str = ""
    released: bool = False

    @property
    def status_text(self) -> str:
        if self.released:
            return "다른 도구가 사용 중"
        if self.index is None:
            return "카메라 없음"
        if not self.connected:
            return self.message or "연결 안 됨"
        if self.infer_fps > 0:
            return f"영상 {self.video_fps:.0f} FPS · 추론 {self.infer_fps:.0f} FPS"
        return f"영상 {self.video_fps:.0f} FPS"


class CameraFeed:
    """카메라 한 대를 소유하고 표시용 프레임을 만든다."""

    def __init__(
        self,
        role_key: str,
        index: int | None,
        name: str = "",
        *,
        model_path: Path | None = None,
    ) -> None:
        self.role_key = role_key
        self._index = index
        self._name = name
        # model_path가 있으면 추론 스레드를 함께 돌린다(검수 캠).
        self._model_path = model_path

        self._lock = threading.Lock()
        self._threads: list[threading.Thread] = []
        self._stop_event = threading.Event()

        self._preview = None  # 표시용 BGR 프레임
        self._raw_frame = None  # 추론·스냅샷용 최신 원본 BGR
        self._raw_seq = 0
        self._last_result = None
        self._video_fps = 0.0
        self._infer_fps = 0.0
        self._released = False
        self._snapshot = CameraSnapshot(index=index, name=name)
        # 운영 중에만 쓰는 기준 개수 덮어쓰기. None이면 설정 파일 값을 그대로
        # 쓴다. 여기서만 들고 있으므로 프로그램을 끄면 설정 파일 값으로 돌아간다.
        self._target_count: int | None = None

    # ------------------------------------------------------------------ 수명주기

    def start(self) -> None:
        if self._index is None:
            self._store(CameraSnapshot(index=None, message="배정된 카메라가 없습니다"))
            return
        if any(thread.is_alive() for thread in self._threads):
            return
        self._stop_event.clear()
        self._threads = [
            threading.Thread(
                target=self._capture_worker, name=f"cam-{self.role_key}", daemon=True
            )
        ]
        if self._model_path is not None:
            self._threads.append(
                threading.Thread(
                    target=self._inference_worker,
                    name=f"cam-{self.role_key}-infer",
                    daemon=True,
                )
            )
        for thread in self._threads:
            thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop_event.set()
        for thread in self._threads:
            if thread.is_alive():
                thread.join(timeout=timeout)
        self._threads = []
        with self._lock:
            self._preview = None
            self._raw_frame = None
            self._last_result = None

    # ------------------------------------------------------------------ 소유권 인계

    def release(self) -> None:
        """카메라를 도구에 넘긴다."""
        with self._lock:
            if self._released:
                return
            self._released = True
        self.stop()
        self._store(
            CameraSnapshot(
                index=self._index,
                name=self._name,
                released=True,
                message="다른 도구가 사용 중",
            )
        )

    def acquire(self) -> None:
        """도구가 끝난 뒤 카메라를 되찾는다."""
        with self._lock:
            if not self._released:
                return
            self._released = False
        self._stop_event.clear()
        self._store(
            CameraSnapshot(
                index=self._index, name=self._name, message="다시 여는 중..."
            )
        )
        self.start()

    @property
    def is_released(self) -> bool:
        with self._lock:
            return self._released

    @property
    def index(self) -> int | None:
        return self._index

    def set_target_count(self, value: int | None) -> None:
        """바구니에 있어야 할 공 개수를 운영 중에만 바꾼다.

        설정 파일(``config/class_scheme.yaml``)은 건드리지 않는다. 프로그램을
        끄면 이 값은 사라지고 다시 설정 파일 값으로 돌아간다.
        """
        with self._lock:
            self._target_count = value

    @property
    def target_count(self) -> int | None:
        with self._lock:
            return self._target_count

    def set_device(self, index: int | None, name: str = "") -> None:
        """사용자가 카메라를 바꿨을 때. 피드를 다시 시작한다."""
        if index == self._index:
            return
        self.stop()
        self._index = index
        self._name = name
        self._store(CameraSnapshot(index=index, name=name))
        if not self.is_released:
            self.start()

    # ------------------------------------------------------------------ 상태 조회

    def snapshot(self) -> CameraSnapshot:
        with self._lock:
            return self._snapshot

    def take_preview(self):
        """마지막 표시용 프레임을 꺼내 온다. 새 프레임이 없으면 None."""
        with self._lock:
            preview, self._preview = self._preview, None
            return preview

    def raw_frame(self):
        """탐지 박스가 없는 최신 원본 프레임(스냅샷용)."""
        with self._lock:
            return self._raw_frame

    def _store(self, snapshot: CameraSnapshot) -> None:
        with self._lock:
            self._snapshot = snapshot

    # ------------------------------------------------------------------ 워커

    def _capture_worker(self) -> None:
        while not self._stop_event.is_set():
            capture = None
            try:
                capture = open_camera(self._index, FEED_WIDTH, FEED_HEIGHT)
                print(f"[camera {self.role_key}] {self._index}번 사용")
                self._capture_loop(capture)
            except Exception as error:
                self._store(
                    CameraSnapshot(
                        index=self._index, name=self._name, message=str(error)
                    )
                )
            finally:
                if capture is not None:
                    capture.release()
            if self._stop_event.wait(RETRY_INTERVAL_SEC):
                break

    def _capture_loop(self, capture) -> None:
        fps = 0.0
        last_time = time.perf_counter()
        while not self._stop_event.is_set():
            grabbed, frame = capture.read()
            if not grabbed:
                raise RuntimeError("카메라 프레임을 읽지 못했습니다.")

            now = time.perf_counter()
            elapsed, last_time = now - last_time, now
            if elapsed > 0:
                fps = 0.9 * fps + 0.1 / elapsed if fps else 1.0 / elapsed

            with self._lock:
                self._raw_frame = frame
                self._raw_seq += 1
                result = self._last_result
                infer_fps = self._infer_fps
                self._video_fps = fps

            if result is not None:
                # plot은 전달한 이미지에 직접 그리므로 원본은 복사해 보호한다.
                annotated = result.plot(img=frame.copy())
                count = 0 if result.boxes is None else len(result.boxes)
                inspection = self._inspection_from(result)
            else:
                annotated, count, inspection = frame, 0, None

            # 크기 조정은 화면에 그리는 VideoPanel이 패널 크기를 보고 한 번만
            # 한다. 여기서 미리 줄이면 두 번 스케일되어 화질만 나빠진다.
            with self._lock:
                self._preview = annotated
                self._snapshot = CameraSnapshot(
                    connected=True,
                    index=self._index,
                    name=self._name,
                    video_fps=fps,
                    infer_fps=infer_fps,
                    detection_count=count,
                    inspection=inspection,
                )

    def _inference_worker(self) -> None:
        from ultralytics import YOLO

        try:
            model = YOLO(str(self._model_path))
        except Exception as error:
            self._store(
                CameraSnapshot(
                    index=self._index,
                    name=self._name,
                    message=f"모델 로드 실패: {error}",
                )
            )
            return

        processed_seq = 0
        while not self._stop_event.is_set():
            with self._lock:
                frame = self._raw_frame
                seq = self._raw_seq
            if frame is None or seq == processed_seq:
                time.sleep(IDLE_SLEEP_SEC)
                continue
            processed_seq = seq

            started = time.perf_counter()
            try:
                result = model(frame, conf=INFERENCE_CONFIDENCE, verbose=False)[0]
            except Exception as error:
                # 한 프레임 추론 실패로 피드를 끊지 않는다.
                print(f"[camera {self.role_key}] 추론 실패: {error}")
                time.sleep(IDLE_SLEEP_SEC)
                continue
            elapsed = time.perf_counter() - started

            with self._lock:
                self._last_result = result
                self._infer_fps = (
                    0.9 * self._infer_fps + 0.1 / elapsed
                    if self._infer_fps
                    else 1.0 / elapsed
                )

    def _inspection_from(self, result) -> InspectionResult | None:
        """추론 결과를 검사 판정으로 바꾼다.

        PASS/REJECT 기준은 ``vision_inspection``에 하나만 있어야 하므로 여기서
        조건을 새로 적지 않고 그 모듈을 그대로 부른다.
        """
        try:
            from vision_inspection.inspection_logic import (
                UNSET,
                count_detections,
                detected_class_names,
            )

            with self._lock:
                override = self._target_count
            # 덮어쓴 값이 없으면 UNSET을 넘겨 설정 파일 값을 쓰게 한다.
            # None을 넘기면 '개수 검사 끄기'라는 다른 뜻이 된다.
            target = UNSET if override is None else override
            return count_detections(detected_class_names(result), target_count=target)
        except Exception:
            return None
