import sys
from pathlib import Path

# common도 ros2_ws/src의 ament 패키지라 저장소 루트에는 없다.
# 나머지 패키지 경로는 pyproject.toml의 pythonpath가 등록한다.
_PROJECT_DIR = Path(__file__).resolve().parents[1]
for _entry in (_PROJECT_DIR, _PROJECT_DIR / "ros2_ws" / "src" / "common"):
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))
