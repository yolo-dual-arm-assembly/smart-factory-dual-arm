"""전 팀이 공유하는 경로와 상태값.

폴더가 담당자별로 나뉘어도 경로와 상태 문자열은 한 곳에서만 정의한다. 각자
자기 폴더에 `"LOADING_COMPLETE"` 같은 문자열을 새로 적으면 오타가 통합 시점에야
드러난다.
"""
import os
from enum import StrEnum
from pathlib import Path

# colcon이 이 패키지를 install/common/lib/pythonX.Y/site-packages/로 복사하므로
# `__file__`에서 고정된 단계 수만큼 거슬러 올라가면 저장소 루트를 놓친다.
# 소스 실행과 colcon 설치 실행 모두에서 같은 곳을 가리켜야 object/·result/·
# models/ 경로가 갈라지지 않는다.
PROJECT_DIR_ENV = "SMART_FACTORY_PROJECT_DIR"
# 저장소 루트에만 함께 있는 표식. 둘 다 있어야 루트로 인정한다.
PROJECT_DIR_MARKERS = ("main.py", "ros2_ws")


def _is_project_dir(candidate: Path) -> bool:
    """저장소 루트인지 표식으로 판별한다."""
    return (candidate / "main.py").is_file() and (candidate / "ros2_ws").is_dir()


def find_project_dir(start: Path | None = None) -> Path:
    """저장소 루트를 찾는다.

    우선순위는 환경변수 → 표식 탐색 → 현재 작업 디렉터리다. colcon으로 설치한
    노드처럼 소스 트리 밖에서 실행할 때는 ``SMART_FACTORY_PROJECT_DIR``로
    루트를 알려 준다.
    """
    override = os.environ.get(PROJECT_DIR_ENV)
    if override:
        return Path(override).expanduser().resolve()
    origin = (Path(__file__) if start is None else start).resolve()
    for candidate in origin.parents:
        if _is_project_dir(candidate):
            return candidate
    return Path.cwd().resolve()


PROJECT_DIR = find_project_dir()
WORKSPACE_SRC = PROJECT_DIR / "ros2_ws" / "src"
INPUT_DIR = PROJECT_DIR / "object"
OUTPUT_DIR = PROJECT_DIR / "result"
MODELS_DIR = PROJECT_DIR / "models"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp"}
PREVIEW_SIZE = (620, 650)
CONFIDENCE_THRESHOLD = 0.1

# 노드 패키지별 리소스 위치. 창과 실행기는 이 경로를 주입받을 수도 있다.
OMX_MODEL_PATH = MODELS_DIR / "yolov8n.pt"
OMX1_CONFIG_DIR = WORKSPACE_SRC / "omx1_loading" / "config"
OMX_CALIBRATION_PATH = OMX1_CONFIG_DIR / "calibration.json"
OMX_TEACHING_PATH = OMX1_CONFIG_DIR / "omx_mouse_teaching.json"
DATASET_CONFIG_PATH = (
    WORKSPACE_SRC / "vision_inspection" / "config" / "data.yaml"
)


class RobotState(StrEnum):
    """공정 상태. 값은 그대로 로그·메시지에 실린다."""

    IDLE = "IDLE"
    LOADING = "LOADING"
    LOADING_COMPLETE = "LOADING_COMPLETE"
    INSPECTING = "INSPECTING"
    PASS = "PASS"
    REJECT = "REJECT"
    MOVING = "MOVING"
    COMPLETE = "COMPLETE"
    ERROR = "ERROR"


class RobotId(StrEnum):
    """로봇 식별자. 적재는 OMX_1, 분류는 OMX_2."""

    LOADING = "OMX_1"
    SORTING = "OMX_2"
