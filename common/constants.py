"""전 팀이 공유하는 경로와 상태값.

폴더가 담당자별로 나뉘어도 경로와 상태 문자열은 한 곳에서만 정의한다. 각자
자기 폴더에 `"LOADING_COMPLETE"` 같은 문자열을 새로 적으면 오타가 통합 시점에야
드러난다.
"""
from enum import StrEnum
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
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
