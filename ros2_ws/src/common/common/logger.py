"""전 모듈 공용 로거.

담당자마다 ``print``를 다르게 쓰면 통합 시점에 어느 모듈이 낸 줄인지 알 수
없다. 모듈 이름과 시각이 항상 앞에 붙도록 로거를 한 곳에서 만든다.
"""
from __future__ import annotations

import logging
import sys

LOG_FORMAT = "%(asctime)s [%(name)s] %(levelname)s %(message)s"
TIME_FORMAT = "%H:%M:%S"


def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """``get_logger(__name__)``으로 쓰는 모듈 로거를 반환한다.

    같은 이름으로 여러 번 불러도 핸들러가 중복 등록되지 않는다.
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(LOG_FORMAT, TIME_FORMAT))
        logger.addHandler(handler)
        logger.propagate = False
    logger.setLevel(level)
    return logger
