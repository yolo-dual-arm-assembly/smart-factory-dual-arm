"""바구니 검사에서 '공'과 '불량'으로 셀 클래스 이름 묶음.

담당: 2번(비전 검사).

학습 데이터셋의 클래스 체계가 아직 확정되지 않았으므로 이름을 코드에 박지
않는다. 이름은 패키지 로컬 설정 ``config/class_scheme.yaml``에서 읽고, 체계가
정해지면 코드 수정 없이 그 파일만 고친다.

체계는 두 모양 중 하나가 된다.

* 정상/불량을 라벨로 나눈 경우(``ball_ok``/``ball_ng``) — 불량도 공 한 개이므로
  ``count_defects_as_balls``가 참이어야 개수가 맞는다.
* 공은 한 클래스, 결함은 별도 영역으로 잡은 경우(``ball``/``defect``) — 결함
  박스는 공 위에 겹쳐 잡히므로 개수에 더하면 이중으로 센다.

이 차이를 클래스 이름만으로는 알 수 없어서 설정에 플래그로 남긴다.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from common.constants import WORKSPACE_SRC
from common.logger import get_logger

logger = get_logger(__name__)

CLASS_SCHEME_PATH = (
    WORKSPACE_SRC / "vision_inspection" / "config" / "class_scheme.yaml"
)


@dataclass(frozen=True)
class ClassScheme:
    """어떤 클래스 이름을 공/불량/이물질로 셀지에 대한 규칙."""

    ball_names: tuple[str, ...] = ("ball",)
    defect_names: tuple[str, ...] = ("defect", "bad_ball")
    # 오투입(공이 아닌 물건). 비어 있으면 오투입 검사를 하지 않는다.
    foreign_names: tuple[str, ...] = ()
    count_defects_as_balls: bool = True

    def is_foreign(self, class_name: str) -> bool:
        """오투입 물체인지. 공도 불량도 아니므로 가장 먼저 본다."""
        return class_name in self.foreign_names

    def is_defect(self, class_name: str) -> bool:
        if self.is_foreign(class_name):
            return False
        return class_name in self.defect_names

    def is_ball(self, class_name: str) -> bool:
        """공 한 개로 셀 클래스인지. 오투입·불량 판정보다 뒤에 본다."""
        if self.is_foreign(class_name):
            return False
        if class_name in self.defect_names:
            return self.count_defects_as_balls
        return class_name in self.ball_names

    @property
    def known_names(self) -> tuple[str, ...]:
        """설정에 적힌 모든 클래스 이름(중복 없이, 적은 순서대로)."""
        seen: dict[str, None] = {}
        for name in (*self.ball_names, *self.defect_names, *self.foreign_names):
            seen.setdefault(name, None)
        return tuple(seen)

    def unknown_names(self, model_names: Iterable[str]) -> tuple[str, ...]:
        """모델이 내놓지 않는 이름을 돌려준다. 오타·체계 불일치를 잡는다."""
        available = set(model_names)
        return tuple(
            name for name in self.known_names if name not in available
        )

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> "ClassScheme":
        """설정 파일에서 읽은 dict를 규칙으로 바꾼다."""
        defaults = cls()
        return cls(
            ball_names=_as_name_tuple(
                mapping.get("ball_names"), defaults.ball_names
            ),
            defect_names=_as_name_tuple(
                mapping.get("defect_names"), defaults.defect_names
            ),
            foreign_names=_as_name_tuple(
                mapping.get("foreign_names"), defaults.foreign_names
            ),
            count_defects_as_balls=bool(
                mapping.get(
                    "count_defects_as_balls", defaults.count_defects_as_balls
                )
            ),
        )


DEFAULT_CLASS_SCHEME = ClassScheme()


def _as_name_tuple(
    value: Any, fallback: tuple[str, ...]
) -> tuple[str, ...]:
    """설정값을 클래스 이름 튜플로 바꾼다.

    항목이 아예 없을 때만 기본값을 쓰고, ``[]``라고 적었으면 빈 목록 그대로
    둔다. "결함 클래스는 아직 없다"는 정당한 설정이라 기본값으로 되살리면
    설정한 사람의 뜻과 달라진다.

    이름 하나만 적어 문자열이 되는 실수(``ball_names: ball``)가 글자 단위로
    쪼개지지 않게 한 겹 감싼다.
    """
    if value is None:
        return fallback
    if isinstance(value, str):
        value = [value]
    return tuple(str(name).strip() for name in value if str(name).strip())


def _read_config(path: Path) -> Mapping[str, Any] | None:
    """설정 파일을 딕셔너리로 읽는다. 실패하면 경고 후 ``None``.

    설정이 없다고 검사가 멈추면 안 되므로 예외를 밖으로 내보내지 않는다.
    """
    try:
        import yaml

        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.warning("검사 설정이 없어 기본값을 씁니다: %s", path)
        return None
    except Exception as error:  # 잘못된 YAML, 권한 문제 등
        logger.warning(
            "검사 설정을 읽지 못해 기본값을 씁니다 (%s): %s", path, error
        )
        return None

    if not isinstance(raw, Mapping):
        logger.warning("검사 설정이 딕셔너리가 아니라 기본값을 씁니다: %s", path)
        return None
    return raw


def load_class_scheme(path: Path = CLASS_SCHEME_PATH) -> ClassScheme:
    """설정 파일을 읽어 규칙을 만든다. 읽지 못하면 기본값으로 계속 간다.

    어떤 규칙으로 세고 있는지는 :func:`describe_scheme`로 확인한다.
    """
    raw = _read_config(path)
    if raw is None:
        return DEFAULT_CLASS_SCHEME
    return ClassScheme.from_mapping(raw)


def load_target_count(path: Path = CLASS_SCHEME_PATH) -> int | None:
    """바구니에 있어야 할 공 개수를 설정에서 읽는다.

    통합 제어기가 아직 기준 수량을 넘겨 주지 않아서, 값을 여기 두고 검사할
    때마다 읽는다. ``null``이거나 값이 없으면 ``None``을 돌려주고, 그러면
    개수 검사를 하지 않는다. 제어기가 값을 넘기기 시작하면 그쪽이 우선이다.
    """
    raw = _read_config(path)
    if raw is None:
        return None
    value = raw.get("target_count")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        logger.warning(
            "target_count가 정수가 아니라 개수 검사를 끕니다: %r", value
        )
        return None


def describe_scheme(scheme: ClassScheme) -> str:
    """로그 한 줄로 보여줄 규칙 요약."""
    return (
        f"ball={list(scheme.ball_names)} "
        f"defect={list(scheme.defect_names)} "
        f"foreign={list(scheme.foreign_names)} "
        f"count_defects_as_balls={scheme.count_defects_as_balls}"
    )


def warn_on_mismatch(
    scheme: ClassScheme, model_names: Iterable[str]
) -> tuple[str, ...]:
    """설정 이름이 모델에 없으면 경고하고 그 이름들을 돌려준다.

    이 불일치는 예외를 내지 않고 '개수 0 → 항상 REJECT'로 조용히 나타나기
    때문에, 검사 시작 시점에 눈에 보이게 만든다.
    """
    model_names = tuple(model_names)
    unknown = scheme.unknown_names(model_names)
    if unknown:
        logger.warning(
            "모델에 없는 클래스 이름입니다 %s. 모델이 아는 이름: %s. "
            "config/class_scheme.yaml을 데이터셋 클래스에 맞추세요. "
            "(그대로 두면 해당 항목은 절대 검출되지 않습니다)",
            list(unknown),
            _summarize_names(model_names),
        )
    return unknown


def _summarize_names(names: tuple[str, ...], limit: int = 12) -> str:
    """모델 클래스 목록을 로그 한 줄에 들어갈 길이로 줄인다.

    사전학습 모델(COCO 80개)로 시험할 때 경고가 화면을 덮지 않게 한다.
    """
    if len(names) <= limit:
        return str(list(names))
    shown = list(names[:limit])
    return f"{shown} 외 {len(names) - limit}개"
