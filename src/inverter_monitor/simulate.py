from __future__ import annotations

import math
import time

from inverter_monitor.catalog import Catalog
from inverter_monitor.decode import encode_physical
from inverter_monitor.memory_map import (
    CAN_ID_OFFSET_ADDRESS,
    DEFAULT_CAN_ID_OFFSET,
    MEMORY_FRAME_ID,
    WatchList,
    pack_memory_frame,
)
from inverter_monitor.transport import CanFrame


class DemoSource:
    """Synthetic PM100DX traffic so the UI can run without hardware."""

    label = "demo"

    def __init__(self, catalog: Catalog, watch_list: WatchList | None = None) -> None:
        self._catalog = catalog
        self._watch = watch_list or WatchList()
        self._t0 = time.monotonic()
        self._pending: list[CanFrame] = []
        self._last_emit = 0.0
        self._tick = 0

    def recv(self, timeout: float) -> CanFrame | None:
        if self._pending:
            return self._pending.pop(0)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            now = time.monotonic()
            if now - self._last_emit >= 0.01:
                self._last_emit = now
                self._pending = self._build_tick(now)
                self._tick += 1
                if self._pending:
                    return self._pending.pop(0)
            time.sleep(0.001)
        return None

    def close(self) -> None:
        self._pending.clear()

    def _elapsed(self, now: float) -> float:
        return now - self._t0

    def _vsm(self, elapsed: float) -> int:
        if elapsed < 0.6:
            return 0
        if elapsed < 1.2:
            return 1
        if elapsed < 2.4:
            return 2
        if elapsed < 3.0:
            return 3
        if elapsed < 4.0:
            return 4
        if elapsed < 5.0:
            return 5
        if int(elapsed) % 28 >= 24:
            return 7
        return 6

    def _faults(self, vsm: int) -> tuple[int, int, int, int]:
        if vsm != 7:
            return (0, 0, 0, 0)
        # Motor over-temperature: RUN bit 44 → Run_Fault_Lo bit 12 → 0x1000
        return (0, 0, 0x1000, 0)

    def _pack(self, name: str, values: dict[str, float | int | bool]) -> bytes:
        return encode_physical(self._catalog.messages_by_name[name], values)

    def _build_tick(self, now: float) -> list[CanFrame]:
        elapsed = self._elapsed(now)
        vsm = self._vsm(elapsed)
        running = vsm == 6
        speed = 0.0 if not running else 1800 + 900 * math.sin(elapsed * 0.7)
        torque_cmd = 0.0 if not running else 35 + 20 * math.sin(elapsed * 0.9)
        torque_fb = torque_cmd * 0.92
        dc_v = 48 + 8 * min(elapsed / 3.0, 1.0) if vsm < 4 else 380 + 4 * math.sin(elapsed * 0.2)
        dc_i = 0.0 if not running else torque_fb * speed / max(dc_v, 1.0) / 9.55
        motor_temp = 32 + elapsed * 0.15 + (8 if running else 0)
        mod_a = 28 + elapsed * 0.08 + (6 if running else 0)
        post_lo, post_hi, run_lo, run_hi = self._faults(vsm)
        inverter_state = 1 if vsm < 5 else (8 if running else 1)
        frames: list[CanFrame] = []

        def emit(name: str, values: dict[str, float | int | bool]) -> None:
            message = self._catalog.messages_by_name[name]
            frames.append(
                CanFrame(
                    timestamp=now,
                    arbitration_id=message.can_id,
                    data=self._pack(name, values),
                )
            )

        emit(
            "M165_Motor_Position_Info",
            {
                "D1_Motor_Angle_Electrical": (elapsed * 120) % 360,
                "D2_Motor_Speed": speed,
                "D3_Electrical_Output_Frequency": abs(speed) / 30.0,
                "D4_Delta_Resolver_Filtered": 0.2,
            },
        )
        emit(
            "M172_Torque_And_Timer_Info",
            {
                "D1_Commanded_Torque": torque_cmd,
                "D2_Torque_Feedback": torque_fb,
                "D3_Power_On_Timer": elapsed,
            },
        )
        emit(
            "M166_Current_Info",
            {
                "D1_Phase_A_Current": dc_i * 0.7,
                "D2_Phase_B_Current": dc_i * -0.4,
                "D3_Phase_C_Current": dc_i * -0.3,
                "D4_DC_Bus_Current": dc_i,
            },
        )
        emit(
            "M167_Voltage_Info",
            {
                "D1_DC_Bus_Voltage": dc_v,
                "D2_Output_Voltage": dc_v * 0.6 if running else 0,
                "D3_VAB_Vd_Voltage": 12 if running else 0,
                "D4_VBC_Vq_Voltage": 18 if running else 0,
            },
        )
        emit(
            "M176_Fast_Info",
            {
                "Fast_Torque_Command": torque_cmd,
                "Fast_Torque_Feedback": torque_fb,
                "Fast_Motor_Speed": speed,
                "Fast_DC_Bus_Voltage": dc_v,
            },
        )

        if self._tick % 10 == 0:
            emit(
                "M160_Temperature_Set_1",
                {
                    "D1_Module_A": mod_a,
                    "D2_Module_B": mod_a - 1.5,
                    "D3_Module_C": mod_a + 0.8,
                    "D4_Gate_Driver_Board": mod_a - 4,
                },
            )
            emit(
                "M162_Temperature_Set_3",
                {
                    "D1_RTD4_Temperature": motor_temp - 3,
                    "D2_RTD5_Temperature": motor_temp - 2,
                    "D3_Motor_Temperature": motor_temp,
                    "D4_Torque_Shudder": 0.1 if running else 0,
                },
            )
            emit(
                "M170_Internal_States",
                {
                    "D1_VSM_State": vsm,
                    "D1_PWM_Frequency": 12,
                    "D2_Inverter_State": inverter_state,
                    "D3_Relay_1_Status": vsm >= 2,
                    "D3_Relay_2_Status": vsm >= 3,
                    "D3_Relay_3_Status": False,
                    "D3_Relay_4_Status": False,
                    "D3_Relay_5_Status": False,
                    "D3_Relay_6_Status": False,
                    "D4_Inverter_Run_Mode": False,
                    "D4_Inverter_Discharge_State": 0,
                    "D5_Inverter_Command_Mode": True,
                    "D5_Rolling_Counter": self._tick % 16,
                    "D6_Inverter_Enable_State": running or vsm == 5,
                    "D6_Start_Mode_Active": vsm == 5,
                    "D6_Inverter_Enable_Lockout": vsm == 7,
                    "D7_Direction_Command": True,
                    "D7_BMS_Active": True,
                    "D7_BMS_Torque_Limiting": running and math.sin(elapsed) > 0.85,
                    "D7_Max_Speed_Limiting": False,
                    "D7_Low_Speed_Limiting": False,
                },
            )
            emit(
                "M171_Fault_Codes",
                {
                    "D1_Post_Fault_Lo": post_lo,
                    "D2_Post_Fault_Hi": post_hi,
                    "D3_Run_Fault_Lo": run_lo,
                    "D4_Run_Fault_Hi": run_hi,
                },
            )
            emit(
                "M163_Analog_Input_Voltages",
                {
                    "D1_Analog_Input_1": 1.2 + (1.8 if running else 0),
                    "D2_Analog_Input_2": 0.4,
                    "D3_Analog_Input_3": 0.0,
                    "D4_Analog_Input_4": 0.0,
                    "D5_Analog_Input_5": 0.0,
                    "D6_Analog_Input_6": 0.0,
                },
            )
            emit(
                "M164_Digital_Input_Status",
                {
                    "D1_Digital_Input_1": True,
                    "D2_Digital_Input_2": vsm >= 4,
                    "D3_Digital_Input_3": False,
                    "D4_Digital_Input_4": False,
                    "D5_Digital_Input_5": False,
                    "D6_Digital_Input_6": False,
                    "D7_Digital_Input_7": False,
                    "D8_Digital_Input_8": False,
                },
            )
            emit(
                "M173_Modulation_And_Flux_Info",
                {
                    "D1_Modulation_Index": 0.72 if running else 0.0,
                    "D2_Flux_Weakening_Output": 4 if running else 0,
                    "D3_Id_Command": -12 if running else 0,
                    "D4_Iq_Command": torque_cmd * 2 if running else 0,
                },
            )
        self._append_memory_watches(frames, now, vsm, speed, torque_cmd, torque_fb)
        return frames

    def _append_memory_watches(
        self,
        frames: list[CanFrame],
        now: float,
        vsm: int,
        speed: float,
        torque_cmd: float,
        torque_fb: float,
    ) -> None:
        for address in self._watch.addresses():
            symbol = self._catalog.memory_by_address.get(address)
            if symbol is None:
                continue
            raw = self._demo_raw(symbol.name, address, vsm, speed, torque_cmd, torque_fb)
            frames.append(
                CanFrame(
                    timestamp=now,
                    arbitration_id=MEMORY_FRAME_ID,
                    data=pack_memory_frame(address, raw & 0xFFFF),
                )
            )

    def _demo_raw(
        self,
        name: str,
        address: int,
        vsm: int,
        speed: float,
        torque_cmd: float,
        torque_fb: float,
    ) -> int:
        if name == "VSM_State":
            return vsm
        if name == "Inverter_Enable":
            return 1 if vsm >= 5 else 0
        if "Commanded_Torque" in name:
            return int(round(torque_cmd * 10)) & 0xFFFF
        if "Feedback_Torque" in name:
            return int(round(torque_fb * 10)) & 0xFFFF
        if "Speed" in name and "EEPROM" not in name:
            return int(round(speed)) & 0xFFFF
        if name == "Code_Version_YYYY":
            return 0x2022
        if name == "Code_Version_MMDD":
            return 0x1118
        if name == "SW_Version":
            return 0x204C
        if name == "CAN_ID_Offset_EEPROM" or address == CAN_ID_OFFSET_ADDRESS:
            return DEFAULT_CAN_ID_OFFSET
        return address & 0xFFFF
