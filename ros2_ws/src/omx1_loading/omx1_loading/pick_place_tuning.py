"""pick & place 속도·높이·그리퍼 튜닝값 — ROS 노드(`loading_node`)와 GUI/CLI
실행기(`pick_ball.OmxVisionRunner`)가 동일한 상수를 쓰도록 한곳에 모았다.
둘 중 하나만 고치고 다른 쪽을 빠뜨리면 같은 로봇인데 동작이 달라지므로
반드시 여기 값을 같이 쓴다.

실기 모터가 Drive Mode(주소 10) bit2=1로 "Time-based Profile"이라
``OmxConfig.profile_velocity``는 rpm이 아니라 목표까지 도달하는 데 걸리는
시간(ms)이다 — 값이 클수록 느리다(0=최대 속도).
"""
from __future__ import annotations

from common.omx_controller import OmxController, gripper_percent_to_dxl

# pick 하강·그립(닫기) 속도만 느리게 유지하고 나머지는 1.5배 빠르게 했다.
PICK_PLACE_PROFILE_VELOCITY = 1700  # 수평 이동/접근 구간
PICK_DESCEND_PROFILE_VELOCITY = 5000  # pick 하강 — 공을 조심스럽게 집어야 해서 안 건드림
PICK_DESCEND_DURATION = 6.0
PLACE_DESCEND_PROFILE_VELOCITY = 3300  # place 하강 — 1.5배 빠르게
PLACE_DESCEND_DURATION = 4.0
SETTLE_WAIT_SEC = 1.0  # pick·place 하강 직전, 흔들림이 멈추길 기다리는 시간
# 공 탐지가 hit_frames만큼 확정된 직후, 바로 움직이지 않고 기다리는 시간.
PRE_MOVE_WAIT_SEC = 1.0

# 그리퍼는 move_xyz와 별개로 자기 속도(ms)를 쓰므로 열고/닫기 직전에
# enable_torque()로 다시 눌러줘야 한다 — 안 그러면 직전 이동 속도가 남아있어
# 그리퍼 동작이 끝나기 전에 다음 동작이 시작돼버린다.
GRIPPER_CLOSE_PROFILE_VELOCITY = 1200  # 그립(닫기)만 그대로 유지
GRIPPER_CLOSE_DURATION = 1.8
GRIPPER_OPEN_PROFILE_VELOCITY = 800  # 열기·놓기는 1.5배 빠르게
GRIPPER_OPEN_DURATION = 1.2

# 바구니에서 그리퍼를 여는 정도. 0=완전 개방, 100=완전 폐쇄(GRIPPER_CLOSE_POS).
# 공을 놓칠 만큼만 벌리면 되는 값이라 실측 후 조정 필요.
PLACE_RELEASE_PERCENT = 40.0
PLACE_RELEASE_DURATION = 1.0

# pick 하강 전 그리퍼를 여는 정도. 완전 개방(0%)하면 탁구공(지름 40mm) 옆에
# 붙어 있는 다른 공을 건드려서, 40mm보다 살짝만 더 벌어지게 값을 높였다.
# 실측 후 조정 필요.
PICK_OPEN_PERCENT = 25.0

# 이동 중 바구니·다른 공을 치지 않도록 접근 높이(approach_z)에 더하는 여유.
# 높을수록 안전하지만 팔의 최대 수평 도달반경이 줄어든다(예: 8cm에서 14cm로
# 올리면 반경이 약 26.4cm→23.1cm로 준다) — 실측하며 절충한다.
APPROACH_Z_MARGIN = 0.03
# pick 하강이 너무 깊어서(테이블에 눌려서) 공이 밀려나는 걸 막는 여유.
PICK_Z_MARGIN = 0.01
# 바구니 바닥을 세게 치지 않도록 place_z(놓는 높이)에 더하는 여유.
PLACE_Z_MARGIN = 0.03

# 캘리브레이션이 일정하게 오른쪽(사용자 기준)으로 치우쳐서 나오는 걸 보정하는 값.
# 실측하며 부호·크기 조정 필요.
Y_OFFSET_CORRECTION_M = -0.015


def gripper_open_and_wait(controller: OmxController) -> None:
    """옆 공을 안 건드리게 완전 개방 대신 PICK_OPEN_PERCENT만큼만 연다."""
    controller.config.profile_velocity = GRIPPER_OPEN_PROFILE_VELOCITY
    controller.enable_torque()  # 그리퍼 속도(ms) 갱신 — 팔은 정지 상태라 안전
    controller.set_gripper_position(gripper_percent_to_dxl(PICK_OPEN_PERCENT))
    _sleep(GRIPPER_OPEN_DURATION)


def gripper_close_and_wait(controller: OmxController) -> None:
    controller.config.profile_velocity = GRIPPER_CLOSE_PROFILE_VELOCITY
    controller.enable_torque()
    controller.gripper_close(duration=GRIPPER_CLOSE_DURATION)


def gripper_release_and_wait(controller: OmxController) -> None:
    # 놓는 동작도 "여는" 쪽이라 GRIPPER_OPEN_PROFILE_VELOCITY(빠른 쪽) 사용.
    controller.config.profile_velocity = GRIPPER_OPEN_PROFILE_VELOCITY
    controller.enable_torque()
    controller.set_gripper_position(gripper_percent_to_dxl(PLACE_RELEASE_PERCENT))
    _sleep(PLACE_RELEASE_DURATION)


def _sleep(seconds: float) -> None:
    import time

    time.sleep(seconds)
