"""웹캠 실시간 YOLO 탐지 데모.

기본 사용(레포 루트에서 실행):
    python -m vision_inspection.detect                     # yolov8n.pt, 카메라 0번
    python -m vision_inspection.detect --model best.pt     # 커스텀 로봇 탐지 모델
    python -m vision_inspection.detect --no-window --max-frames 1   # 창 없이 1프레임 캡처 테스트

창에서 q 또는 ESC로 종료, s로 현재 프레임을 result/에 저장한다.
탐지 성공/실패 flag(ros2 파이프라인과 동일한 기준: 박스 유무)를 화면 좌상단에 표시한다.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import cv2
from ultralytics import YOLO

from common.camera import open_camera, open_preferred_camera
from common.constants import MODELS_DIR, OMX_MODEL_PATH, OUTPUT_DIR

DEFAULT_MODEL = OMX_MODEL_PATH
WINDOW_TITLE = "YOLO Webcam (q/ESC: quit, s: snapshot)"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="웹캠 영상을 YOLO로 실시간 탐지합니다.")
    parser.add_argument(
        "--model",
        type=Path,
        default=DEFAULT_MODEL,
        help="가중치(.pt) 경로 (기본: yolov8n.pt, 커스텀 모델은 best.pt)",
    )
    parser.add_argument("--conf", type=float, default=0.5, help="탐지 신뢰도 임계값")
    parser.add_argument(
        "--camera",
        type=int,
        default=None,
        help="카메라 인덱스 (기본: USB 외장캠 우선 자동 선택)",
    )
    parser.add_argument("--width", type=int, default=1280, help="캡처 가로 해상도")
    parser.add_argument("--height", type=int, default=720, help="캡처 세로 해상도")
    parser.add_argument(
        "--max-frames",
        type=int,
        default=0,
        help="지정 프레임 수만 처리 후 종료 (0이면 무제한)",
    )
    parser.add_argument(
        "--no-window",
        action="store_true",
        help="창 없이 실행하고 마지막 프레임을 result/webcam_frame.jpg로 저장",
    )
    return parser.parse_args()


def draw_overlay(frame, detected: bool, fps: float) -> None:
    flag_text = "DETECTED" if detected else "NO DETECT"
    flag_color = (0, 200, 0) if detected else (0, 0, 255)
    cv2.putText(
        frame, flag_text, (12, 34), cv2.FONT_HERSHEY_SIMPLEX, 1.0, flag_color, 2
    )
    cv2.putText(
        frame,
        f"{fps:.1f} FPS",
        (12, 66),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (255, 255, 255),
        2,
    )


def main() -> None:
    args = parse_args()
    model_path = args.model if args.model.is_absolute() else MODELS_DIR / args.model
    if not model_path.is_file():
        raise SystemExit(f"모델 파일이 없습니다: {model_path}")

    model = YOLO(model_path)
    try:
        if args.camera is None:
            capture, camera_index = open_preferred_camera(args.width, args.height)
        else:
            capture = open_camera(args.camera, args.width, args.height)
            camera_index = args.camera
    except RuntimeError as error:
        raise SystemExit(str(error)) from None
    actual_w = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(
        f"model={model_path.name} conf={args.conf} "
        f"camera={camera_index} capture={actual_w}x{actual_h}"
    )

    OUTPUT_DIR.mkdir(exist_ok=True)
    frame_count = 0
    fps = 0.0
    annotated = None
    try:
        while True:
            grabbed, frame = capture.read()
            if not grabbed:
                print("프레임을 읽지 못했습니다. 종료합니다.")
                break

            started = time.perf_counter()
            result = model(frame, conf=args.conf, verbose=False)[0]
            elapsed = time.perf_counter() - started
            fps = 0.9 * fps + 0.1 * (1.0 / elapsed) if fps else 1.0 / elapsed

            detected = result.boxes is not None and len(result.boxes) > 0
            annotated = result.plot()
            draw_overlay(annotated, detected, fps)

            frame_count += 1
            if args.no_window:
                print(
                    f"[{frame_count}] detected={detected} "
                    f"({len(result.boxes) if detected else 0} objects, {elapsed * 1000:.0f}ms)"
                )
            else:
                cv2.imshow(WINDOW_TITLE, annotated)
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):  # q 또는 ESC
                    break
                if key == ord("s"):
                    snapshot = OUTPUT_DIR / f"webcam_snapshot_{frame_count}.jpg"
                    cv2.imwrite(str(snapshot), annotated)
                    print(f"저장: {snapshot}")

            if args.max_frames and frame_count >= args.max_frames:
                break
    finally:
        capture.release()
        cv2.destroyAllWindows()

    if args.no_window and annotated is not None:
        output_path = OUTPUT_DIR / "webcam_frame.jpg"
        cv2.imwrite(str(output_path), annotated)
        print(f"마지막 프레임 저장: {output_path}")


if __name__ == "__main__":
    main()
