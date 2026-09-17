from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from inverter_monitor.catalog import Catalog, graph_lookup_keys, mode_label
from inverter_monitor.store import (
    StoreSnapshot,
    command_mode,
    first_signal,
    get_signal,
    mechanical_power_kw,
)
from inverter_monitor.ui.theme import CARD_MARGINS, PAGE_MARGINS
from inverter_monitor.ui.widgets import Card, FlagChip, MetricCard

# CAN M170 packed bits with no dedicated Memory View bool. Hide on RS232.
_CAN_ONLY_FLAGS = ("lockout", "bms", "max_spd", "low_spd")

_RS232_RELAYS = (
    "MemoryView.RLY1_Precharge_Output_Status",
    "MemoryView.RLY2_Main_Output_Status",
    "MemoryView.RLY3_OK_Output_Status",
    "MemoryView.RLY4_Fault_Output_Status",
)
_RS232_DINS = (
    "MemoryView.DIN1_Forward_Switch",
    "MemoryView.DIN2_Reverse_Switch",
    "MemoryView.DIN3_Brake_Switch",
    "MemoryView.DIN4_Regen_Disable_Switch",
    "MemoryView.DIN5_Ignition_Input",
    "MemoryView.DIN6_Start_Input",
    "MemoryView.DIN7_Switch",
    "MemoryView.DIN8_Switch",
)


class OverviewPage(QWidget):
    def __init__(self, catalog: Catalog, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._catalog = catalog
        self.cards = [
            MetricCard("Motor speed", *graph_lookup_keys("M165_Motor_Position_Info.D2_Motor_Speed")),
            MetricCard(
                "Torque feedback",
                *graph_lookup_keys("M172_Torque_And_Timer_Info.D2_Torque_Feedback"),
            ),
            MetricCard(
                "Torque command",
                *graph_lookup_keys("M172_Torque_And_Timer_Info.D1_Commanded_Torque"),
            ),
            MetricCard("DC bus voltage", *graph_lookup_keys("M167_Voltage_Info.D1_DC_Bus_Voltage")),
            MetricCard("DC bus current", *graph_lookup_keys("M166_Current_Info.D4_DC_Bus_Current")),
            MetricCard(
                "Motor temp",
                *graph_lookup_keys("M162_Temperature_Set_3.D3_Motor_Temperature"),
            ),
            MetricCard("Module A temp", *graph_lookup_keys("M160_Temperature_Set_1.D1_Module_A")),
        ]
        self.power = MetricCard("Mech. power")

        grid = QGridLayout()
        grid.setSpacing(8)
        items = self.cards + [self.power]
        for index, card in enumerate(items):
            grid.addWidget(card, index // 3, index % 3)

        self.flags = {
            "lockout": FlagChip("LOCKOUT"),
            "bms": FlagChip("BMS LIM"),
            "max_spd": FlagChip("MAX SPD"),
            "low_spd": FlagChip("LOW SPD"),
            "discharge": FlagChip("DISCHARGE"),
        }
        flag_row = QHBoxLayout()
        for chip in self.flags.values():
            flag_row.addWidget(chip)
        flag_row.addStretch()

        self.relays = QLabel("Relays —")
        self.dins = QLabel("DINs —")
        self.relays.setObjectName("muted")
        self.dins.setObjectName("muted")

        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(8)
        left.addLayout(grid)
        left.addLayout(flag_row)
        left.addWidget(self.relays)
        left.addWidget(self.dins)
        left.addStretch()
        left_wrap = QWidget()
        left_wrap.setLayout(left)

        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        detail_card = Card()
        detail_layout = QVBoxLayout(detail_card)
        detail_layout.setContentsMargins(*CARD_MARGINS)
        heading = QLabel("Current VSM")
        heading.setObjectName("muted")
        detail_layout.addWidget(heading)
        detail_layout.addWidget(self.detail)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_wrap)
        splitter.addWidget(detail_card)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        root = QVBoxLayout(self)
        root.setContentsMargins(*PAGE_MARGINS)
        root.addWidget(splitter)

    def update_from(self, snapshot: StoreSnapshot, source: str = "RS232") -> None:
        rs232 = source == "RS232"
        for name, chip in self.flags.items():
            chip.setVisible(not rs232 or name not in _CAN_ONLY_FLAGS)

        for card in self.cards:
            card.update_from(snapshot)
        power = mechanical_power_kw(snapshot)
        self.power._value.setText("—" if power is None else f"{power:.1f}")
        self.power._unit.setText("kW")

        def flag(key: str) -> bool | None:
            signal = get_signal(snapshot, key)
            if signal is None:
                return None
            return bool(signal.value)

        if not rs232:
            self.flags["lockout"].set_state(flag("M170_Internal_States.D6_Inverter_Enable_Lockout"))
            self.flags["bms"].set_state(flag("M170_Internal_States.D7_BMS_Torque_Limiting"))
            self.flags["max_spd"].set_state(flag("M170_Internal_States.D7_Max_Speed_Limiting"))
            self.flags["low_spd"].set_state(flag("M170_Internal_States.D7_Low_Speed_Limiting"))
        discharge = first_signal(
            snapshot,
            "M170_Internal_States.D4_Inverter_Discharge_State",
            "MemoryView.Inverter_Discharge_State",
        )
        self.flags["discharge"].set_state(
            None if discharge is None or discharge.raw is None else bool(discharge.raw)
        )

        if rs232:
            self._set_bits(self.relays, "Relays 1–4", _RS232_RELAYS, snapshot)
            self._set_bits(self.dins, "DINs", _RS232_DINS, snapshot)
        else:
            relay_keys = [f"M170_Internal_States.D3_Relay_{index}_Status" for index in range(1, 7)]
            din_keys = [f"M164_Digital_Input_Status.D{index}_Digital_Input_{index}" for index in range(1, 9)]
            self._set_bits(self.relays, "Relays", relay_keys, snapshot)
            self._set_bits(self.dins, "DINs", din_keys, snapshot)

        vsm = first_signal(
            snapshot,
            "M170_Internal_States.D1_VSM_State",
            "MemoryView.VSM_State",
        )
        if vsm is None or vsm.raw is None:
            self.detail.setPlainText("Waiting for VSM")
            return
        state = self._catalog.vsm_states.get(int(vsm.raw))
        if state is None:
            self.detail.setPlainText(f"ID {vsm.raw}: {vsm.enum_name or 'unknown'}\n{vsm.enum_description or ''}")
            return
        mode = command_mode(snapshot)
        description, entry, exit = state.text(mode)
        lines = [
            f"{state.id}  {state.name}  ({mode_label(mode)} wording)",
            description,
            "",
            f"Entry: {entry or '—'}",
            f"Exit: {exit or '—'}",
        ]
        if state.conditions:
            lines.append("Conditions:")
            lines.extend(f"  • {item}" for item in state.conditions)
        if state.lockouts:
            lines.append("Lockouts / notes:")
            lines.extend(f"  • {item}" for item in state.lockouts)
        self.detail.setPlainText("\n".join(lines))

    @staticmethod
    def _set_bits(
        label: QLabel,
        title: str,
        keys: tuple[str, ...] | list[str],
        snapshot: StoreSnapshot,
    ) -> None:
        signals = [get_signal(snapshot, key) for key in keys]
        if not any(signal is not None and signal.raw is not None for signal in signals):
            label.setText(f"{title} —")
            return
        bits = []
        for signal in signals:
            if signal is None or signal.raw is None:
                bits.append("—")
            else:
                bits.append("●" if signal.value else "○")
        label.setText(f"{title}  " + " ".join(bits))
