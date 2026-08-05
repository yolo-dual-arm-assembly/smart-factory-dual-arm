import io
import sys
from pathlib import Path

from common.bootstrap import (
    DEVELOPMENT_PYTHON,
    MINIMUM_PYTHON,
    REQUIRED_MODULES,
    _guidance,
    candidate_interpreters,
    ensure_runtime,
    interpreter_is_ready,
    is_mingw_python,
    missing_modules,
    python_is_supported,
    report,
    venv_interpreter,
)


def test_python_is_supported_compares_minimum() -> None:
    assert python_is_supported(MINIMUM_PYTHON)
    assert python_is_supported((99, 0))
    assert not python_is_supported((3, 8))


def test_development_python_satisfies_minimum() -> None:
    assert DEVELOPMENT_PYTHON[:2] >= MINIMUM_PYTHON


def test_missing_modules_reports_only_absent_names() -> None:
    absent = missing_modules(("sys", "json", "definitely_not_a_real_module"))

    assert absent == ["definitely_not_a_real_module"]


def test_required_modules_are_importable_in_this_environment() -> None:
    """테스트가 도는 Python이라면 앱도 실행할 수 있어야 한다."""
    assert missing_modules(REQUIRED_MODULES) == []


def test_is_mingw_python_detects_msys2_build() -> None:
    msys = is_mingw_python(
        executable=r"C:\msys64\ucrt64\bin\python.exe",
        version="3.14.5 (main) [MINGW GCC UCRT 16.1.0 64 bit (AMD64)]",
    )
    standard = is_mingw_python(
        executable=r"C:\Users\me\AppData\Local\Programs\Python\Python311\python.exe",
        version="3.11.9 (tags/v3.11.9) [MSC v.1938 64 bit (AMD64)]",
    )

    assert msys is True
    assert standard is False


def test_venv_interpreter_finds_platform_specific_path(tmp_path: Path) -> None:
    scripts = tmp_path / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / "python.exe").write_text("", encoding="utf-8")

    assert venv_interpreter(tmp_path) == scripts / "python.exe"


def test_venv_interpreter_returns_none_without_venv(tmp_path: Path) -> None:
    assert venv_interpreter(tmp_path) is None


def test_candidate_interpreters_exclude_current_interpreter() -> None:
    current = Path(sys.executable).resolve()

    assert current not in candidate_interpreters()


def test_interpreter_is_ready_accepts_this_interpreter() -> None:
    assert interpreter_is_ready(sys.executable) is True


def test_interpreter_is_ready_rejects_missing_executable(tmp_path: Path) -> None:
    assert interpreter_is_ready(tmp_path / "no_such_python") is False


def test_ensure_runtime_is_a_noop_when_dependencies_exist() -> None:
    """의존성이 갖춰진 환경에서는 재실행 없이 즉시 반환해야 한다."""
    assert ensure_runtime() is None


class _NarrowStream(io.StringIO):
    """한글을 표현하지 못하는 콘솔을 흉내 낸다."""

    encoding = "ascii"

    def write(self, text: str) -> int:
        text.encode("ascii")  # 표현할 수 없으면 UnicodeEncodeError
        return super().write(text)


def test_report_survives_console_without_korean_support() -> None:
    """안내 문구 인코딩 때문에 실행이 죽어서는 안 된다."""
    stream = _NarrowStream()

    report("의존성이 설치된 Python으로 실행합니다", stream=stream)

    assert stream.getvalue().strip() != ""


def test_report_writes_message_when_encoding_allows() -> None:
    stream = io.StringIO()

    report("한글 안내", stream=stream)

    assert "한글 안내" in stream.getvalue()


def test_linux_guidance_uses_project_venv_instead_of_system_pip() -> None:
    guidance = _guidance(
        ["tkinter", "PIL", "cv2", "ultralytics"], platform="linux"
    )

    assert "Python 3.11 이상" in guidance
    assert "개발 기준: 3.11.9" in guidance
    assert "sudo apt install -y python3-venv python3-tk" in guidance
    assert ".venv/bin/python" in guidance
    assert "Python: Select Interpreter" in guidance
    assert "지금 이 Python에 그대로 설치" not in guidance
