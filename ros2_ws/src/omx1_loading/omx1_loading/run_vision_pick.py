"""적재 로봇(OMX_1) 비전 이동 CLI.

레포 루트에서 모듈로 실행한다::

    # 1. 연결 테스트 (모터 스캔, 홈 이동)
    python -m omx1_loading.run_vision_pick --test-connection

    # 2. 캘리브레이션 (픽셀↔로봇 좌표 4점 매핑)
    python -m omx1_loading.run_vision_pick --calibrate

    # 3. 비전 제어 실행 (탐지 → 접근만)
    python -m omx1_loading.run_vision_pick --run --model best.pt --class robot

    # 4. 전체 Pick & Place 실행
    python -m omx1_loading.run_vision_pick --run --model best.pt --class robot --full-pickplace

    # 5. 특정 XYZ로 이동 테스트 (단위: cm)
    python -m omx1_loading.run_vision_pick --move 20 0 10
"""
from __future__ import annotations

import argparse
import sys

from omx1_loading.coordinate_transform import OmxCalibration
from common.constants import OMX_CALIBRATION_PATH
from common.omx_controller import OmxController, OmxConfig
from common.serial_ports import default_omx_port


# 경로는 담당 폴더마다 따로 적지 않고 common.constants 한 곳에서 가져온다.
CALIBRATION_FILE = OMX_CALIBRATION_PATH
# 리눅스(/dev/ttyACM0)와 윈도우(COMx)에서 모두 동작하도록 자동 선택한다.
DEFAULT_PORT = default_omx_port()


def cmd_test_connection(args: argparse.Namespace) -> None:
    """연결 테스트: 포트 열기 → 모터 스캔 → 홈 이동."""
    config = OmxConfig(port=args.port)
    ctrl = OmxController(config)
    try:
        ctrl.connect()
        print("\n=== 모터 스캔 (ID 1~20) ===")
        found = ctrl.scan_motors(range(1, 21))
        if found:
            print(f"→ 발견된 모터 ID: {found}")
            print("\n=== 홈 포즈로 이동 ===")
            ctrl.home(duration=2.0)
            print("✅ 연결 테스트 성공!")
        else:
            print("⚠️  모터를 찾지 못했습니다.")
            print("   확인사항:")
            print("   1. OMX 전원/USB 연결 상태")
            print("   2. 포트 권한: sudo usermod -a -G dialout $USER")
            print(f"   3. 현재 포트: {args.port} (--port 옵션으로 변경 가능)")
    finally:
        ctrl.disconnect()


def cmd_calibrate(args: argparse.Namespace) -> None:
    """대화형 캘리브레이션: 4점 픽셀↔로봇 좌표 수집."""
    import cv2
    import numpy as np

    print("=== OMX 캘리브레이션 ===")
    print("테이블 위에 마커 4개를 놓고, 각 마커에서 로봇 좌표(cm)를 입력하세요.")
    print("카메라 창에서 마커를 클릭하면 픽셀 좌표가 자동 기록됩니다.\n")

    config = OmxConfig(port=args.port)
    ctrl = OmxController(config)
    cal = OmxCalibration(pick_z=args.pick_z / 100.0)  # cm → m

    clicked_pixels: list[tuple[int, int]] = []
    frame_ref: list[object] = [None]  # mutable reference for callback

    def on_click(event: int, x: int, y: int, *_: object) -> None:
        if event == cv2.EVENT_LBUTTONDOWN:
            clicked_pixels.append((x, y))
            print(f"  → 픽셀 클릭: ({x}, {y})")

    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        print(f"카메라 {args.camera}번을 열 수 없습니다.")
        return

    cv2.namedWindow("Calibration")
    cv2.setMouseCallback("Calibration", on_click)

    n_points = 4
    robot_coords: list[tuple[float, float]] = []

    print(f"{n_points}개 마커의 로봇 좌표를 미리 입력합니다 (단위: cm):")
    for i in range(n_points):
        try:
            raw = input(f"  마커 {i+1} 로봇 XY (예: 20 0): ").strip().split()
            rx, ry = float(raw[0]) / 100.0, float(raw[1]) / 100.0
            robot_coords.append((rx, ry))
        except (ValueError, IndexError):
            print("입력 오류. 캘리브레이션을 종료합니다.")
            cap.release()
            return

    print(f"\n카메라 창에서 마커 {n_points}개를 순서대로 클릭하세요. (q: 종료)")

    while len(clicked_pixels) < n_points:
        ret, frame = cap.read()
        if not ret:
            break

        # 클릭된 점 표시
        for idx, (px, py) in enumerate(clicked_pixels):
            cv2.circle(frame, (px, py), 8, (0, 255, 0), -1)
            cv2.putText(frame, str(idx + 1), (px + 10, py),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

        remaining = n_points - len(clicked_pixels)
        cv2.putText(frame, f"마커 {len(clicked_pixels)+1}/{n_points} 클릭 대기",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 200, 255), 2)
        cv2.imshow("Calibration", frame)

        key = cv2.waitKey(1)
        if key & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()

    if len(clicked_pixels) < n_points:
        print("충분한 점을 클릭하지 않아 캘리브레이션을 종료합니다.")
        return

    for pixel, robot_xy in zip(clicked_pixels, robot_coords):
        cal.add_point(pixel=pixel, robot_xy=robot_xy)

    try:
        cal.compute()
        err = cal.reprojection_error()
        print(f"✅ 캘리브레이션 완료! 재투영 오차: {err*100:.2f} cm")
        cal.save(CALIBRATION_FILE)
    except Exception as exc:
        print(f"❌ 캘리브레이션 오류: {exc}")


def cmd_run(args: argparse.Namespace) -> None:
    """비전 제어 실행."""
    from omx1_loading.pick_ball import OmxVisionRunner, State

    if not CALIBRATION_FILE.exists():
        raise RuntimeError(
            f"캘리브레이션 파일 없음: {CALIBRATION_FILE}\n"
            "안전을 위해 로봇 이동을 차단했습니다. 먼저 실행하세요:\n"
            f"  {sys.executable} -m omx1_loading.run_vision_pick --calibrate"
        )
    cal = OmxCalibration.load(CALIBRATION_FILE)

    max_stage = State.HOME if args.full_pickplace else State.APPROACH
    config = OmxConfig(port=args.port)

    runner = OmxVisionRunner(
        model_path=args.model,
        calibration=cal,
        config=config,
        target_class=args.cls,
        confidence=args.conf,
        camera_index=args.camera,
        max_stage=max_stage,
    )
    runner.run()


def cmd_move(args: argparse.Namespace) -> None:
    """XYZ 이동 테스트 (단위: cm → 내부에서 m로 변환)."""
    x, y, z = args.move[0] / 100.0, args.move[1] / 100.0, args.move[2] / 100.0
    config = OmxConfig(port=args.port)
    ctrl = OmxController(config)
    try:
        ctrl.connect()
        print(f"→ XYZ 이동: ({x:.3f}m, {y:.3f}m, {z:.3f}m)")
        ctrl.move_xyz(x, y, z, duration=2.0)
        print("✅ 이동 완료. 3초 후 홈으로 복귀...")
        import time; time.sleep(3)
        ctrl.home()
    finally:
        ctrl.disconnect()


def _make_dummy_calibration() -> OmxCalibration:
    """캘리브레이션 없이 테스트용 선형 매핑 Homography 생성."""
    import cv2, numpy as np
    cal = OmxCalibration(pick_z=0.015)
    # 640×480 카메라 기준 간단 선형 매핑 (실제 캘리브레이션 후 교체)
    cal.add_point(pixel=(160, 120), robot_xy=(0.25,  0.10))
    cal.add_point(pixel=(480, 120), robot_xy=(0.25, -0.10))
    cal.add_point(pixel=(160, 360), robot_xy=(0.15,  0.10))
    cal.add_point(pixel=(480, 360), robot_xy=(0.15, -0.10))
    cal.compute()
    print("⚠️  더미 캘리브레이션 사용 중 — 실제 로봇 좌표와 다를 수 있습니다.")
    return cal


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="ROBOTIS OMX 로봇팔 제어 데모",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--port",
        default=DEFAULT_PORT,
        help="시리얼 포트 (기본: 연결된 USB 시리얼 포트 자동 선택)",
    )
    p.add_argument("--camera", type=int, default=0, help="웹캠 인덱스 (기본: 0)")

    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--test-connection", action="store_true", help="연결 테스트 & 홈 이동")
    group.add_argument("--calibrate", action="store_true", help="픽셀↔로봇 캘리브레이션")
    group.add_argument("--run", action="store_true", help="비전 제어 실행")
    group.add_argument("--move", nargs=3, type=float, metavar=("X", "Y", "Z"),
                       help="XYZ 이동 테스트 (단위: cm)")

    # --run 전용 옵션
    p.add_argument("--model", default="best.pt", help="YOLO 모델 경로")
    p.add_argument("--class", dest="cls", default=None, help="탐지할 클래스 이름")
    p.add_argument("--conf", type=float, default=0.5, help="신뢰도 임계값")
    p.add_argument("--full-pickplace", action="store_true",
                   help="전체 Pick & Place 실행 (기본: 접근만)")

    # --calibrate 전용 옵션
    p.add_argument("--pick-z", type=float, default=1.5,
                   help="Pick 높이 cm (캘리브레이션용, 기본: 1.5cm)")

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.test_connection:
        cmd_test_connection(args)
    elif args.calibrate:
        cmd_calibrate(args)
    elif args.run:
        cmd_run(args)
    elif args.move:
        cmd_move(args)


if __name__ == "__main__":
    main()
