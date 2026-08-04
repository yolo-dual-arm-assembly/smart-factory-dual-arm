"""전 모듈이 함께 쓰는 상수·메시지 규격·장치 접근 코드.

거의 모든 모듈이 이 패키지를 먼저 import하므로, 실행 환경 호환 패치도 여기에 둔다.
"""
import pathlib
import sys

# Python 3.13에서 학습된 checkpoint(best.pt 등)를 Python 3.12 이하 환경에서 unpickle할 때
# pathlib._local 모듈 참조 에러가 발생하는 것을 방지하기 위한 호환성 패치
if not hasattr(pathlib, "_local"):
    sys.modules["pathlib._local"] = pathlib
