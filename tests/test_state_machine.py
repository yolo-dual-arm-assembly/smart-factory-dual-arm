import pytest

from common.constants import RobotState
from system_coordinator.state_machine import InvalidTransition, StateMachine


def test_full_cycle_returns_to_idle() -> None:
    machine = StateMachine()
    for state in (
        RobotState.LOADING,
        RobotState.LOADING_COMPLETE,
        RobotState.INSPECTING,
        RobotState.PASS,
        RobotState.MOVING,
        RobotState.COMPLETE,
        RobotState.IDLE,
    ):
        machine.move_to(state)

    assert machine.state is RobotState.IDLE
    assert machine.history[0] is RobotState.IDLE


def test_skipping_a_step_is_rejected() -> None:
    machine = StateMachine()

    with pytest.raises(InvalidTransition):
        machine.move_to(RobotState.INSPECTING)


def test_error_is_reachable_from_working_states() -> None:
    machine = StateMachine()
    machine.move_to(RobotState.LOADING)

    assert machine.fail() is RobotState.ERROR
    assert machine.reset() is RobotState.IDLE


@pytest.mark.parametrize("state", tuple(RobotState))
def test_fail_is_safe_from_every_state(state: RobotState) -> None:
    machine = StateMachine(state)

    assert machine.fail() is RobotState.ERROR
    assert machine.fail() is RobotState.ERROR
