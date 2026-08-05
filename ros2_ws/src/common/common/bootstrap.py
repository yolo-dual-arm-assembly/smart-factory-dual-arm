"""실행 전 Python 런타임 점검과 자동 전환.

윈도우와 리눅스 모두 Python이 여러 개 깔려 있는 경우가 흔하다. VS Code의
실행 버튼, 터미널, 가상환경이 서로 다른 Python을 고르면 앱은
``ModuleNotFoundError`` 한 줄만 남기고 끝나서 무엇을 고쳐야 하는지 알기 어렵다.

그래서 ``main.py``는 무거운 import를 하기 전에 이 모듈을 먼저 부른다. 현재
Python으로 실행할 수 있으면 아무 일도 하지 않고, 그렇지 않으면 의존성이
설치된 다른 Python을 찾아 넘긴다. 넘길 곳이 없을 때만 무엇을 해야 하는지
안내하고 멈춘다. 표준 라이브러리만 사용한다.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

from common.constants import find_project_dir

MINIMUM_PYTHON = (3, 11)
# 프로젝트 개발 기준 버전이다. 패치 버전까지 고정하지는 않으며 3.11 이상을
# 지원한다.
DEVELOPMENT_PYTHON = (3, 11, 9)
# tkinter는 GUI, 나머지는 이미지 처리와 추론에 반드시 필요하다.
REQUIRED_MODULES = ("tkinter", "PIL", "cv2", "ultralytics")
# 자동 전환이 되풀이되지 않도록 넘겨받은 프로세스에 표시를 남긴다.
RELAUNCH_FLAG = "YOLO_APP_RELAUNCHED"
# 이 파일도 ros2_ws/src/common/common/에 있으므로 고정 단계 수로 루트를 잡을 수
# 없다. 판별 규칙은 common.constants 한 곳에만 둔다.
PROJECT_DIR = find_project_dir()
# 윈도우 스토어 별칭은 실제 Python이 아니라 설치 안내를 띄우는 껍데기다.
EXCLUDED_PATH_HINTS = ("windowsapps",)
# ROS2 관례상 패키지 안에 같은 이름의 모듈 폴더가 있다(pkg/pkg/*.py).
# 따라서 import 경로에 올려야 하는 것은 바깥쪽 패키지 폴더다.
WORKSPACE_SRC = PROJECT_DIR / "ros2_ws" / "src"


def workspace_package_dirs(src: Path = WORKSPACE_SRC) -> list[Path]:
    """``ros2_ws/src`` 안에서 파이썬 모듈을 담은 패키지 폴더를 찾는다."""
    if not src.is_dir():
        return []
    return sorted(
        package
        for package in src.iterdir()
        if package.is_dir() and (package / package.name).is_dir()
    )


def ensure_workspace_path(src: Path = WORKSPACE_SRC) -> list[Path]:
    """ROS2 없이 실행할 때도 패키지를 import할 수 있도록 경로를 등록한다.

    ``colcon build`` 뒤에는 ROS2가 같은 경로를 잡아 주지만, 윈도우 개발 PC나
    테스트에서는 ROS2 없이 GUI와 로직만 돌리는 일이 훨씬 많다.
    """
    added: list[Path] = []
    for package in workspace_package_dirs(src):
        entry = str(package)
        if entry not in sys.path:
            sys.path.insert(0, entry)
            added.append(package)
    return added


def report(message: str, stream=None) -> None:
    """인코딩이 좁은 콘솔에서도 안내가 앱을 죽이지 않도록 출력한다.

    출력이 파일이나 파이프로 넘어가면 콘솔이 아닌 로캘 인코딩이 쓰여
    한글에서 ``UnicodeEncodeError``가 날 수 있다. 안내 문구 때문에 실행이
    실패하는 일은 없어야 하므로 표현할 수 없는 글자는 대체한다.
    """
    target = sys.stderr if stream is None else stream
    try:
        print(message, file=target)
    except UnicodeEncodeError:
        encoding = getattr(target, "encoding", None) or "ascii"
        safe = message.encode(encoding, errors="replace").decode(encoding)
        print(safe, file=target)


def python_is_supported(version: tuple[int, ...] = sys.version_info[:2]) -> bool:
    """현재 Python 버전이 최소 요구 버전을 만족하는지 확인한다."""
    return tuple(version[:2]) >= MINIMUM_PYTHON


def missing_modules(modules: Iterable[str] = REQUIRED_MODULES) -> list[str]:
    """import할 수 없는 필수 모듈 이름을 반환한다.

    ``find_spec``은 모듈을 실제로 실행하지 않아 확인 비용이 거의 없다.
    """
    from importlib.util import find_spec

    absent: list[str] = []
    for name in modules:
        try:
            found = find_spec(name) is not None
        except (ImportError, ValueError):
            found = False
        if not found:
            absent.append(name)
    return absent


def is_mingw_python(executable: str = sys.executable, version: str = sys.version) -> bool:
    """MSYS2/MinGW로 빌드된 Python인지 확인한다.

    PyPI가 배포하는 torch·opencv 휠은 표준 CPython ABI용이라 이 Python에는
    설치되지 않는다. 즉 pip로도 해결할 수 없는 환경이다.
    """
    haystack = f"{executable} {version}".casefold()
    return any(tag in haystack for tag in ("msys", "mingw"))


def venv_interpreter(project_dir: Path = PROJECT_DIR) -> Path | None:
    """프로젝트 가상환경의 Python 실행 파일을 OS에 맞게 찾는다."""
    for relative in ("Scripts/python.exe", "bin/python", "bin/python3"):
        candidate = project_dir / ".venv" / relative
        if candidate.is_file():
            return candidate
    return None


def _py_launcher_interpreters() -> list[Path]:
    """윈도우 ``py -0p``가 알려 주는 설치된 Python 목록을 읽는다."""
    launcher = shutil.which("py")
    if launcher is None:
        return []
    try:
        result = subprocess.run(
            [launcher, "-0p"], capture_output=True, text=True, timeout=15
        )
    except (OSError, subprocess.SubprocessError):
        return []

    found: list[Path] = []
    for line in result.stdout.splitlines():
        # 경로에 공백이 있을 수 있어 토큰 분리 대신 경로 모양으로 찾는다.
        match = re.search(r"[A-Za-z]:\\.*python\.exe", line)
        if match is not None:
            found.append(Path(match.group(0)))
    return found


def _is_excluded(executable: Path) -> bool:
    lowered = str(executable).casefold()
    return any(hint in lowered for hint in EXCLUDED_PATH_HINTS)


def candidate_interpreters() -> list[Path]:
    """현재 Python을 대신할 후보를 우선순위대로 반환한다."""
    candidates: list[Path] = []
    project_venv = venv_interpreter()
    if project_venv is not None:
        candidates.append(project_venv)

    if sys.platform.startswith("win"):
        candidates.extend(_py_launcher_interpreters())
        names = ("python.exe", "python3.exe")
    else:
        names = ("python3", "python")
    for name in names:
        located = shutil.which(name)
        if located:
            candidates.append(Path(located))

    current = Path(sys.executable).resolve()
    unique: list[Path] = []
    seen = {current}
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved in seen or _is_excluded(resolved):
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


def _readiness_check_script() -> str:
    return (
        "import sys\n"
        "from importlib.util import find_spec\n"
        f"if sys.version_info[:2] < {MINIMUM_PYTHON!r}:\n"
        "    raise SystemExit(1)\n"
        f"for name in {list(REQUIRED_MODULES)!r}:\n"
        "    try:\n"
        "        found = find_spec(name) is not None\n"
        "    except Exception:\n"
        "        found = False\n"
        "    if not found:\n"
        "        raise SystemExit(1)\n"
        "raise SystemExit(0)\n"
    )


def interpreter_is_ready(executable: Path | str) -> bool:
    """해당 Python으로 앱을 실행할 수 있는지 확인한다."""
    try:
        result = subprocess.run(
            [str(executable), "-c", _readiness_check_script()],
            capture_output=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _linux_setup_guidance(absent: list[str]) -> list[str]:
    """Linux 첫 실행에 필요한 가상환경 설치 절차를 반환한다."""
    tested = ".".join(str(part) for part in DEVELOPMENT_PYTHON)
    venv_python = PROJECT_DIR / ".venv" / "bin" / "python"
    python_command = sys.executable if python_is_supported() else "python3.11"

    lines = [
        f"이 프로젝트는 Python 3.11 이상이 필요합니다(개발 기준: {tested}).",
        "Linux에서는 시스템 Python에 pip 패키지를 직접 설치하지 않고",
        "프로젝트 전용 가상환경(.venv)을 사용하십시오.",
        "",
    ]
    if not python_is_supported():
        lines += [
            "먼저 배포판에 맞는 방법으로 Python 3.11 이상을 설치하십시오.",
            "아래 python3.11은 설치한 Python 3.11 이상의 실행 파일로 바꿔도 됩니다.",
            "",
        ]

    if "tkinter" in absent:
        lines += [
            "1. Tkinter와 가상환경 도구 설치",
            "  Debian/Ubuntu:",
            "    sudo apt update",
            "    sudo apt install -y python3-venv python3-tk",
            "  Fedora:",
            "    sudo dnf install -y python3-tkinter",
            "",
        ]

    step = "2" if "tkinter" in absent else "1"
    lines += [
        f"{step}. 프로젝트 가상환경 생성 및 의존성 설치",
        f'    cd "{PROJECT_DIR}"',
        f'    "{python_command}" -m venv .venv',
        f'    "{venv_python}" -m pip install --upgrade pip',
        f'    "{venv_python}" -m pip install -r requirements.txt',
        "",
        f"{int(step) + 1}. VS Code에서 가상환경 선택",
        "    Ctrl+Shift+P -> Python: Select Interpreter",
        f"    {venv_python}",
        "",
        "선택한 뒤 main.py의 실행 버튼을 다시 누르십시오.",
    ]
    return lines


def _guidance(absent: list[str], platform: str | None = None) -> str:
    lines = [
        "",
        "이 Python으로는 앱을 실행할 수 없습니다.",
        f"  실행 중인 Python : {sys.executable}",
        f"  버전             : {sys.version.split()[0]}",
    ]
    if not python_is_supported():
        minimum = ".".join(str(part) for part in MINIMUM_PYTHON)
        lines.append(f"  문제             : Python {minimum} 이상이 필요합니다.")
    if absent:
        lines.append(f"  없는 모듈        : {', '.join(absent)}")
    lines.append("")

    current_platform = sys.platform if platform is None else platform
    if is_mingw_python():
        lines += [
            "MSYS2/MinGW Python은 이 앱에 사용할 수 없습니다. pip로도 해결되지",
            "않습니다. PyPI의 torch·opencv 휠은 표준 CPython(win_amd64) ABI용이라",
            "설치되지 않고, torch는 MSYS2 빌드 자체가 없습니다.",
            "python.org 배포판이나 프로젝트 가상환경을 사용하십시오.",
            "  https://www.python.org/downloads/",
        ]
    elif current_platform.startswith("linux"):
        lines += _linux_setup_guidance(absent)
    else:
        lines += [
            "의존성을 설치하려면 지금 이 Python에 그대로 설치하십시오.",
            f'  "{sys.executable}" -m pip install -r requirements.txt',
        ]
    lines.append("")
    return "\n".join(lines)


def ensure_runtime(argv: list[str] | None = None) -> None:
    """실행 가능한 Python을 보장한다.

    현재 Python으로 충분하면 아무 것도 하지 않는다. 아니면 의존성이 설치된
    Python으로 같은 명령을 넘기고, 그런 Python이 없으면 안내 후 종료한다.
    """
    absent = missing_modules()
    if not absent and python_is_supported():
        return

    # 넘겨받은 프로세스가 또 부족하면 더 시도해도 같은 결과다.
    if os.environ.get(RELAUNCH_FLAG):
        report(_guidance(absent))
        raise SystemExit(1)

    command_argv = list(sys.argv if argv is None else argv)
    for executable in candidate_interpreters():
        if not interpreter_is_ready(executable):
            continue
        report(f"[bootstrap] 의존성이 설치된 Python으로 실행합니다: {executable}")
        environment = dict(os.environ)
        environment[RELAUNCH_FLAG] = "1"
        completed = subprocess.run(
            [str(executable), *command_argv], env=environment
        )
        raise SystemExit(completed.returncode)

    report(_guidance(absent))
    raise SystemExit(1)
