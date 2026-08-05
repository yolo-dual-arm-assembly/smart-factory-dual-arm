"""YOLO·웹캠·OMX 통합 데스크톱 애플리케이션 실행 진입점.

윈도우와 리눅스 모두 ``python main.py``로 실행한다. 의존성이 없는 Python으로
실행하면 아래 점검이 의존성을 갖춘 Python을 찾아 대신 실행한다.

노드 코드는 ``ros2_ws/src/<패키지>/<패키지>/``에 있다. ROS2를 설치하지 않은
개발 PC에서도 GUI가 그대로 열리도록 실행 전에 import 경로를 등록한다.
"""

import sys
from pathlib import Path

# common도 ros2_ws/src의 ament 패키지라 저장소 루트에는 없다. 나머지 패키지
# 경로는 ensure_workspace_path()가 등록하지만, 그 함수 자체가 common 안에
# 있으므로 여기서 한 번만 직접 올린다.
_COMMON_SRC = Path(__file__).resolve().parent / "ros2_ws" / "src" / "common"
if str(_COMMON_SRC) not in sys.path:
    sys.path.insert(0, str(_COMMON_SRC))

from common.bootstrap import ensure_runtime, ensure_workspace_path  # noqa: E402

# viewer는 Pillow·OpenCV·ultralytics를 import하므로 런타임 점검 뒤에 부른다.
ensure_runtime()
ensure_workspace_path()

from system_monitor.ui.viewer import main  # noqa: E402


if __name__ == "__main__":
    main()
