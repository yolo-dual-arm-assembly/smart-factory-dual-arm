"""YOLO로 컴퓨터 마우스를 찾아 OMX를 물체 위 안전 높이까지 이동한다.

VS Code에서 이 파일을 열고 ``Run Python File`` 버튼으로 실행할 수 있다.
Q: 종료 및 홈 복귀, R: 홈 복귀 후 다음 mouse 다시 탐지.
"""
from __future__ import annotations

from common.constants import OMX_MODEL_PATH, OMX_TEACHING_PATH
from common.omx_controller import OmxConfig
from common.serial_ports import default_omx_port
from omx1_loading.imitation_control import OmxTaughtVisionRunner
from omx1_loading.teaching import OmxTeachingDataset


# 경로는 담당 폴더마다 따로 적지 않고 common.constants 한 곳에서 가져온다.
MODEL_PATH = OMX_MODEL_PATH
TEACHING_PATH = OMX_TEACHING_PATH
# 리눅스(/dev/ttyACM0)와 윈도우(COMx)에서 모두 동작하도록 자동 선택한다.
ROBOT_PORT = default_omx_port()
CAMERA_INDEX = 0


def main() -> None:
    if not MODEL_PATH.is_file():
        raise FileNotFoundError(f"YOLO 모델 파일 없음: {MODEL_PATH}")
    if not TEACHING_PATH.is_file():
        raise RuntimeError(
            f"Mouse 교시 파일 없음: {TEACHING_PATH}\n"
            "메인 GUI(python main.py)의 'Mouse 관절 교시 모드'에서 먼저 교시하세요."
        )

    teaching = OmxTeachingDataset.load(TEACHING_PATH)
    runner = OmxTaughtVisionRunner(
        model_path=MODEL_PATH,
        teaching=teaching,
        config=OmxConfig(port=ROBOT_PORT),
        confidence=0.5,
        hit_frames=5,
        camera_index=CAMERA_INDEX,
    )
    runner.run()


if __name__ == "__main__":
    main()
