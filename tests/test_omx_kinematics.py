"""역기구학 및 좌표 변환 단위 테스트 (하드웨어 없이 실행 가능)."""
from __future__ import annotations

import math
import pytest

from common.omx_controller import (
    JOINT_LIMITS,
    PROFILE_VELOCITY,
    GRIPPER_CLOSE_POS,
    GRIPPER_OPEN_POS,
    OmxConfig,
    OmxController,
    ik_5dof,
    fk_5dof,
    interpolate_joint_angles,
    validate_joint_angles,
    gripper_percent_to_dxl,
    angle_to_dxl,
    dxl_to_angle,
    DXL_CENTER_POSITION,
    OMX_L1,
    OMX_L2,
    OMX_L0,
)
from omx1_loading.coordinate_transform import OmxCalibration, make_full_frame_calibration
from omx1_loading.pick_ball import (
    OmxVisionRunner,
    State,
    is_safe_approach_target,
    validate_calibration_workspace,
    validate_pick_place_plan,
)


# ---------------------------------------------------------------------------
# 역기구학 테스트
# ---------------------------------------------------------------------------
class TestIK:
    def test_home_position(self) -> None:
        """팔 정면 중간 위치에 대한 IK가 수렴하는지 확인."""
        angles = ik_5dof(x=0.20, y=0.00, z=0.10)
        assert len(angles) == 5
        # Joint 1 은 0 (정면)
        assert abs(angles[0]) < 0.01

    def test_symmetry_left_right(self) -> None:
        """좌우 대칭 위치의 Joint 1이 반전되는지 확인."""
        a_left  = ik_5dof(x=0.20, y= 0.05, z=0.10)
        a_right = ik_5dof(x=0.20, y=-0.05, z=0.10)
        assert abs(a_left[0] + a_right[0]) < 0.01

    def test_reachability_boundary(self) -> None:
        """비전 작업 영역의 바깥쪽 목표도 계산 가능한지 확인."""
        angles = ik_5dof(x=0.23, y=0.0, z=0.08)
        assert angles is not None

    def test_unreachable_raises(self) -> None:
        """도달 불가능한 위치에서 ValueError가 발생하는지 확인."""
        with pytest.raises(ValueError, match="도달 불가능"):
            ik_5dof(x=1.0, y=0.0, z=0.0)  # 1m 는 도달 불가

    def test_forward_kinematics_consistency(self) -> None:
        """IK 결과로 FK를 계산하면 원래 위치와 가까운지 확인."""
        target_x, target_y, target_z = 0.18, 0.05, 0.12
        angles = ik_5dof(x=target_x, y=target_y, z=target_z)
        fx, fy, fz = fk_5dof(angles)

        assert fx == pytest.approx(target_x, abs=1e-6)
        assert fy == pytest.approx(target_y, abs=1e-6)
        assert fz == pytest.approx(target_z, abs=1e-6)



# ---------------------------------------------------------------------------
# 각도 변환 테스트
# ---------------------------------------------------------------------------
class TestAngleConversion:
    def test_center_angle(self) -> None:
        """0 라디안은 DXL 중앙값(2048)이어야 한다."""
        assert angle_to_dxl(0.0) == DXL_CENTER_POSITION

    def test_positive_angle(self) -> None:
        """양수 각도는 2048보다 큰 값이어야 한다."""
        assert angle_to_dxl(math.pi / 2) > DXL_CENTER_POSITION

    def test_roundtrip(self) -> None:
        """각도 → DXL → 각도 변환이 가역적이어야 한다."""
        for deg in [-90, -45, 0, 45, 90]:
            rad = math.radians(deg)
            dxl = angle_to_dxl(rad)
            recovered = dxl_to_angle(dxl)
            assert abs(recovered - rad) < 0.01, f"{deg}° 왕복 변환 오차"

    def test_clamp_range(self) -> None:
        """±π를 초과해도 0~4095 범위로 클램핑되어야 한다."""
        assert 0 <= angle_to_dxl(10.0) <= 4095
        assert 0 <= angle_to_dxl(-10.0) <= 4095

    def test_quantized_joint_limits_stay_inside_soft_limits(self) -> None:
        """경계 각도를 모터 단위로 바꿔도 소프트 리밋 밖으로 나가지 않는다."""
        for lower, upper in JOINT_LIMITS:
            quantized_lower = dxl_to_angle(angle_to_dxl(lower))
            quantized_upper = dxl_to_angle(angle_to_dxl(upper))

            assert lower <= quantized_lower <= upper
            assert lower <= quantized_upper <= upper


class TestOmxConfig:
    def test_default_profile_velocity_is_slow_and_limited(self) -> None:
        """GUI 홈 이동은 제한 없는 속도(0)나 고속 값을 사용하지 않는다."""
        assert PROFILE_VELOCITY == 30
        assert OmxConfig().profile_velocity == PROFILE_VELOCITY


class TestOmxControllerFailurePropagation:
    def test_move_xyz_propagates_unreachable_target(self) -> None:
        controller = OmxController()

        with pytest.raises(ValueError, match="도달 불가능"):
            controller.move_xyz(1.0, 0.0, 0.0)


class TestJointSoftLimits:
    def test_accepts_inclusive_joint_boundaries(self) -> None:
        lower = [limit[0] for limit in JOINT_LIMITS]
        upper = [limit[1] for limit in JOINT_LIMITS]

        assert validate_joint_angles(lower) == lower
        assert validate_joint_angles(upper) == upper

    @pytest.mark.parametrize("joint_index", range(5))
    @pytest.mark.parametrize("side", ["lower", "upper"])
    def test_identifies_joint_outside_limit(
        self,
        joint_index: int,
        side: str,
    ) -> None:
        angles = [0.0] * 5
        limit = JOINT_LIMITS[joint_index][0 if side == "lower" else 1]
        angles[joint_index] = limit + (-0.001 if side == "lower" else 0.001)

        with pytest.raises(ValueError, match=rf"Joint {joint_index + 1} 한계 초과"):
            validate_joint_angles(angles)

    @pytest.mark.parametrize("invalid", [math.nan, math.inf, -math.inf])
    def test_rejects_non_finite_angle(self, invalid: float) -> None:
        angles = [0.0] * 5
        angles[2] = invalid

        with pytest.raises(ValueError, match="Joint 3.*유한한 숫자"):
            validate_joint_angles(angles)

    def test_direct_move_rejects_target_before_connection(self) -> None:
        controller = OmxController()

        with pytest.raises(ValueError, match="Joint 2 한계 초과"):
            controller.move_joints([0.0, math.pi, 0.0, 0.0, 0.0])

    def test_smooth_move_rejects_target_before_connection(self) -> None:
        controller = OmxController()

        with pytest.raises(ValueError, match="Joint 4 한계 초과"):
            controller.move_joints_smooth(
                [0.0, 0.0, 0.0, math.pi, 0.0],
            )


class TestGripperConversion:
    def test_calibrated_endpoints(self) -> None:
        assert gripper_percent_to_dxl(0) == GRIPPER_OPEN_POS
        assert gripper_percent_to_dxl(100) == GRIPPER_CLOSE_POS

    def test_midpoint_and_clamping(self) -> None:
        assert gripper_percent_to_dxl(50) == 2300
        assert gripper_percent_to_dxl(-10) == GRIPPER_OPEN_POS
        assert gripper_percent_to_dxl(110) == GRIPPER_CLOSE_POS


class TestJointInterpolation:
    def test_interpolation_reaches_target_in_small_steps(self) -> None:
        start = [0.0, 0.0]
        target = [1.0, -2.0]

        result = interpolate_joint_angles(start, target, steps=4)

        assert result == [
            [0.25, -0.5],
            [0.5, -1.0],
            [0.75, -1.5],
            [1.0, -2.0],
        ]

    def test_interpolation_rejects_invalid_steps(self) -> None:
        with pytest.raises(ValueError, match="1 이상"):
            interpolate_joint_angles([0.0], [1.0], steps=0)


# ---------------------------------------------------------------------------
# 캘리브레이션 테스트
# ---------------------------------------------------------------------------
class TestCalibration:
    def _make_calibration(self) -> OmxCalibration:
        """테스트용 4점 캘리브레이션 객체를 생성한다."""
        cal = OmxCalibration(pick_z=0.015)
        cal.add_point(pixel=(160, 120), robot_xy=(0.25,  0.10))
        cal.add_point(pixel=(480, 120), robot_xy=(0.25, -0.10))
        cal.add_point(pixel=(160, 360), robot_xy=(0.15,  0.10))
        cal.add_point(pixel=(480, 360), robot_xy=(0.15, -0.10))
        cal.compute()
        return cal

    def test_compute_succeeds(self) -> None:
        """4점 이상이면 Homography 계산이 성공해야 한다."""
        cal = self._make_calibration()
        assert cal.is_ready

    def test_pixel_to_robot_known_point(self) -> None:
        """알려진 픽셀 좌표의 변환 결과가 기대값에 가까워야 한다."""
        cal = self._make_calibration()
        rx, ry, rz = cal.pixel_to_robot(160, 120)
        assert abs(rx - 0.25) < 0.005
        assert abs(ry - 0.10) < 0.005
        assert rz == pytest.approx(0.015)

    def test_center_pixel(self) -> None:
        """이미지 중앙 픽셀이 로봇 중앙 부근으로 변환되어야 한다."""
        cal = self._make_calibration()
        rx, ry, _ = cal.pixel_to_robot(320, 240)
        # 중앙은 X≈0.20, Y≈0.00 에 가까워야 함
        assert 0.14 < rx < 0.26
        assert -0.05 < ry < 0.05

    def test_save_load_roundtrip(self, tmp_path: object) -> None:
        """저장→불러오기 후 동일한 변환 결과를 내야 한다."""
        import pathlib
        cal = self._make_calibration()
        path = pathlib.Path(str(tmp_path)) / "test_cal.json"
        cal.save(path)

        cal2 = OmxCalibration.load(path)
        r1 = cal.pixel_to_robot(320, 240)
        r2 = cal2.pixel_to_robot(320, 240)
        assert abs(r1[0] - r2[0]) < 1e-6
        assert abs(r1[1] - r2[1]) < 1e-6

    def test_insufficient_points_raises(self) -> None:
        """3점 이하로 compute() 시 ValueError가 발생해야 한다."""
        cal = OmxCalibration()
        cal.add_point((0, 0), (0.1, 0.1))
        cal.add_point((100, 0), (0.2, 0.1))
        cal.add_point((0, 100), (0.1, 0.2))
        with pytest.raises(ValueError, match="최소 4개"):
            cal.compute()

    def test_point_view_and_remove_last(self) -> None:
        cal = OmxCalibration()
        cal.add_point((10, 20), (0.1, 0.2))
        cal.add_point((30, 40), (0.2, 0.3))

        assert cal.point_count == 2
        assert cal.pixel_points == ((10, 20), (30, 40))

        cal.remove_last_point()

        assert cal.point_count == 1
        assert cal.pixel_points == ((10, 20),)
        assert cal.robot_points == ((0.1, 0.2),)

    def test_full_frame_calibration_maps_corners_and_center(self) -> None:
        cal = make_full_frame_calibration(1280, 720)

        assert cal.pixel_to_robot(0, 0)[:2] == pytest.approx((0.23, 0.08))
        assert cal.pixel_to_robot(1279, 719)[:2] == pytest.approx((0.18, -0.08))
        assert cal.pixel_to_robot(639.5, 359.5)[:2] == pytest.approx(
            (0.205, 0.0)
        )


class TestVisionSafety:
    def test_accepts_reachable_table_target(self) -> None:
        assert is_safe_approach_target(0.20, 0.0, 0.08)

    @pytest.mark.parametrize(
        "target",
        [(0.05, 0.0, 0.08), (0.30, 0.0, 0.08), (0.20, 0.20, 0.08)],
    )
    def test_rejects_target_outside_workspace(
        self, target: tuple[float, float, float]
    ) -> None:
        assert not is_safe_approach_target(*target)

    def test_rejects_calibration_points_with_wrong_units(self) -> None:
        cal = OmxCalibration()
        cal.add_point((100, 100), (2.5, 3.4))

        with pytest.raises(ValueError, match="다시 설정"):
            validate_calibration_workspace(cal)

    def test_rejects_place_position_outside_workspace(self) -> None:
        cal = OmxCalibration(place_pos=(1.0, 0.0))

        with pytest.raises(ValueError, match="배치 접근 목표가 작업 영역 밖"):
            validate_calibration_workspace(cal)

    def test_rejects_unreachable_place_height(self) -> None:
        cal = OmxCalibration(place_pos=(0.2, 0.0), place_z=1.0)

        with pytest.raises(ValueError, match="배치 목표를 실행할 수 없습니다"):
            validate_calibration_workspace(cal)

    def test_full_plan_is_validated_before_first_robot_command(self) -> None:
        class RecordingController:
            def __init__(self) -> None:
                self.commands: list[str] = []

            def move_joints_smooth(self, *_args, **_kwargs) -> None:
                self.commands.append("move_joints_smooth")

            def move_xyz(self, *_args, **_kwargs) -> None:
                self.commands.append("move_xyz")

            def gripper_close(self, *_args, **_kwargs) -> None:
                self.commands.append("gripper_close")

            def gripper_open(self, *_args, **_kwargs) -> None:
                self.commands.append("gripper_open")

            def home(self, *_args, **_kwargs) -> None:
                self.commands.append("home")

        calibration = OmxCalibration(pick_z=1.0)
        controller = RecordingController()
        runner = object.__new__(OmxVisionRunner)
        runner.calibration = calibration
        runner.controller = controller
        runner.max_stage = State.HOME

        with pytest.raises(ValueError, match="물체 집기 목표를 실행할 수 없습니다"):
            runner._execute_action((0.2, 0.0, calibration.pick_z))

        assert controller.commands == []

    def test_valid_pick_place_plan_passes(self) -> None:
        calibration = OmxCalibration()

        validate_pick_place_plan((0.2, 0.0, calibration.pick_z), calibration)
