#!/usr/bin/env python3
"""Generate reference YAML from Cascadia Motion Software User Manual V3.6."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DOCS = ROOT / "docs"

SOURCE_PDF = "/Users/rrxie/Downloads/Software User Manual (V3_6) For Inverter.pdf"
MANUAL_VERSION = "V3.6"


def dump(path: Path, data: dict) -> None:
    path.write_text(
        yaml.dump(
            data,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
            width=120,
        ),
        encoding="utf-8",
    )


def build_vsm_states() -> dict:
    return {
        "manual_version": MANUAL_VERSION,
        "source_pdf": SOURCE_PDF,
        "pages": [31, 32, 33, 34, 35, 36, 38, 39],
        "symbol": "VSM_State",
        "description": (
            "Internal vehicle state machine tracked at startup, shutdown, and operational transitions. "
            "Monitored via the VSM_State symbol in RMS GUI Memory View."
        ),
        "states": [
            {
                "id": 0,
                "name": "Start State",
                "description": "Default state at vehicle power-up.",
                "notes": {
                    "entry": "Vehicle powered up; default state unless program enable input is held low at power-up.",
                    "exit": "Proceeds through initialization, EEPROM load, and POST.",
                    "substeps": [
                        "12V Power-up: processor and I/O initialization; default parameter list created.",
                        "Load from EEPROM: application parameters and factory calibrations loaded.",
                        "Power on Self-Test (POST): hardware/sensor validation; each test has an associated fault flag.",
                    ],
                },
                "related_lockouts": [
                    "Program enable input held low at power-up prevents entering the Vehicle State Machine.",
                ],
            },
            {
                "id": 1,
                "name": "Pre-charge sequence initial state",
                "description": "Turn on the pre-charge relay.",
                "notes": {
                    "entry": "Pre-charge Initialization (VSM_State = 1).",
                    "exit": "If DC voltage below software over-voltage threshold, pre-charge output activated and transition to state 2.",
                    "conditions": [
                        "Declares VDC Out-of-range high fault if DC voltage is above the software over-voltage threshold (not user-adjustable).",
                    ],
                },
                "related_lockouts": [],
            },
            {
                "id": 2,
                "name": "Pre-charge sequence active state",
                "description": "Waiting for capacitor to finish charging.",
                "notes": {
                    "entry": "Pre-charge Active (VSM_State = 2).",
                    "exit": "If charge rate stays within range, Main output activated and Pre-charge output deactivated.",
                    "conditions": [
                        "Declares VDC Out-of-range high fault if DC voltage exceeds software over-voltage threshold.",
                        "After 3 s max pre-charge time: VDC Out-of-range low fault if below DC Under-voltage threshold EEPROM; pre-charge timeout fault if still charging.",
                    ],
                },
                "related_lockouts": [],
            },
            {
                "id": 3,
                "name": "Pre-charge sequence finish state",
                "description": "Completes final checks before proceeding to Wait State.",
                "notes": {
                    "entry": "Pre-charge Complete (VSM_State = 3).",
                    "exit": "Proceeds to Wait State if capacitor charge is stable.",
                    "conditions": [
                        "Declares relevant fault if over/under-charged or voltage changes quickly after pre-charge output deactivation.",
                    ],
                },
                "related_lockouts": [],
            },
            {
                "id": 4,
                "name": "Wait State",
                "description": "Waiting for activation of forward or reverse.",
                "notes": {
                    "entry": "Checks Key Switch Mode (EEPROM Key_Switch_Mode_EEPROM).",
                    "exit": "Transitions when brake/direction/start conditions satisfied.",
                    "key_switch_mode_0": [
                        "Simple on/off ignition: brake active and exactly one of /FORWARD or /REVERSE active.",
                        "Both /FORWARD and /REVERSE active declares FWD_RVS_INVALID_STATE_FAULT.",
                    ],
                    "key_switch_mode_1": [
                        "Traditional ignition: brake active, start signal pulse received, one direction active while brakes held.",
                        "Both /FORWARD and /REVERSE active declares FWD_RVS_INVALID_STATE_FAULT.",
                    ],
                },
                "related_lockouts": [
                    "FWD_RVS_INVALID_STATE_FAULT when both forward and reverse switches active.",
                    "Precharge_Bypassed_EEPROM = 1 skips pre-charge and goes directly to Wait State at power-up.",
                ],
            },
            {
                "id": 5,
                "name": "Ready State",
                "description": "Activates the inverter state machine to begin energizing the motor.",
                "notes": {
                    "entry": "Sends Enable Inverter Command; waits for Inverter Ready Flag.",
                    "exit": "Auto-transitions if no faults and inverter enables within timeout.",
                    "conditions": [
                        "Declares inverter state timeout fault if inverter does not enable within allowed time (2 minutes per Appendix N).",
                    ],
                },
                "related_lockouts": [],
            },
            {
                "id": 6,
                "name": "Motor Running State",
                "description": "Normal motor running operation.",
                "notes": {
                    "entry": "Normal running after Ready State.",
                    "exit": "Fault, shutdown, or mode transition.",
                    "conditions": [
                        "Drive may switch between torque and speed command mode within operating envelope.",
                    ],
                },
                "related_lockouts": [],
            },
            {
                "id": 7,
                "name": "Fault State",
                "description": "The controller has faulted.",
                "notes": {
                    "entry": "Fault during POST or while running.",
                    "exit": "Fault cleared via Clear Faults Command (GUI or CAN); some faults require power recycle.",
                    "conditions": [
                        "Fault indicator blinks one fault at a time; POST faults have higher priority than RUN faults.",
                        "POST faults followed by two quick blinks to distinguish from RUN faults.",
                    ],
                },
                "related_lockouts": [
                    "Hardware Gate/Desaturation Fault (POST and RUN) cannot be cleared via Clear Fault Command; requires power recycle.",
                    "EEPROM Update Required (POST warning) not cleared by Clear Faults Command.",
                ],
            },
            {
                "id": 14,
                "name": "Shutdown in Process",
                "description": "Inverter shutdown in process.",
                "notes": {
                    "entry": "Key switch mode 1: user turned key switch off (ignition input held low).",
                    "exit": None,
                },
                "related_lockouts": [],
            },
            {
                "id": 15,
                "name": "Recycle Power State",
                "description": "Power must be recycled after EEPROM programming.",
                "notes": {
                    "entry": "EEPROM programming successfully completed.",
                    "exit": "Controller must be re-powered for new EEPROM values to take effect.",
                },
                "related_lockouts": [],
            },
        ],
        "state_id_gaps": "States 8–13 are not defined in this manual.",
        "inverter_states": {
            "symbol": "Inverter_Mode",
            "pages": [36, 72],
            "description": "Inverter internal states (inv_mode) referenced in Ready State and GUI Display Parameters.",
            "states": [
                {"id": 0, "name": "Precharge, power-up state"},
                {"id": 1, "name": "Stop", "description": "Inverter not running; STOP state."},
                {"id": 2, "name": "Open Loop State", "description": "For testing purposes."},
                {"id": 3, "name": "Closed Loop state", "description": "Normal state."},
                {"id": 4, "name": "Start Time Delay", "description": "Small delay before starting the inverter."},
                {"id": 5, "name": "Current Sensor Test", "description": "Flux ramp and flux regulators enabled."},
                {"id": 6, "name": "Closed Loop Torque", "description": "Torque regulator enabled."},
                {"id": 7, "name": "Torque Ramp", "description": "Start torque ramp."},
                {"id": 8, "name": "Idle Run", "description": "Inverter running normally."},
                {"id": 9, "name": "Idle Stop", "description": "Inverter stopped."},
                {"id": 10, "name": "Ramp Off Torque", "description": "Ramps down torque command."},
                {"id": 11, "name": "Ramp Off Flux", "description": "Ramps down flux command."},
                {"id": 12, "name": "All Ramps Off", "description": "Shutoff inverter."},
                {"id": 15, "name": "Default – Stop state"},
            ],
            "state_id_gaps": "States 13 and 14 are not defined in this manual.",
        },
        "diagram_notes": [
            "Document describes linear startup: Start (0) → Pre-charge (1→2→3) → Wait (4) → Ready (5) → Motor Running (6).",
            "Fault State (7) entered from POST or run-time faults.",
            "Shutdown in Process (14) and Recycle Power (15) are terminal/administrative states.",
            "Manual references section 11 for VSM_State and section 11.4 for Inverter_Mode; those sections are not present in revision 3.6.",
        ],
    }


def post_fault_bits() -> list[dict]:
    rows = [
        (0, 0, "Hardware Gate/Desaturation Fault", "00000001", "fault"),
        (0, 1, "HW Over-current Fault", "00000002", "fault"),
        (0, 2, "Accelerator input shorted to ground", "00000004", "fault"),
        (0, 3, "Accelerator input open or shorted to 5V", "00000008", "fault"),
        (0, 4, "Current Sensor Low", "00000010", "fault"),
        (0, 5, "Current Sensor High", "00000020", "fault"),
        (0, 6, "Module Temperature Low", "00000040", "fault"),
        (0, 7, "Module Temperature High", "00000080", "fault"),
        (1, 8, "Control PCB Temperature Low", "00000100", "fault"),
        (1, 9, "Control PCB Temperature High", "00000200", "fault"),
        (1, 10, "Gate Drive PCB Temperature Low", "00000400", "fault"),
        (1, 11, "Gate Drive PCB Temperature High", "00000800", "fault"),
        (1, 12, "5V Sense Voltage Low", "00001000", "fault"),
        (1, 13, "5V Sense Voltage High", "00002000", "fault"),
        (1, 14, "12V Sense Voltage Low", "00004000", "fault"),
        (1, 15, "12V Sense Voltage High", "00008000", "fault"),
        (2, 16, "Internal 2.5V Reference Voltage Low", "00010000", "fault"),
        (2, 17, "Internal 2.5V Reference Voltage High", "00020000", "fault"),
        (2, 18, "Internal 1.5V Reference Voltage Low", "00040000", "fault"),
        (2, 19, "Internal 1.5V Sense Voltage High", "00080000", "fault"),
        (2, 20, "DC Bus Voltage High", "00100000", "fault"),
        (2, 21, "DC Bus Voltage Low", "00200000", "fault"),
        (2, 22, "Pre-charge Timeout", "00400000", "fault"),
        (2, 23, "Pre-charge Voltage Failure", "00800000", "fault"),
        (3, 24, "EEPROM Checksum Invalid", "01000000", "fault"),
        (3, 25, "EEPROM Data Out of Range", "02000000", "fault"),
        (3, 26, "EEPROM Update Required", "04000000", "warning"),
        (3, 27, "Reserved", "08000000", "info"),
        (3, 28, "Reserved", "10000000", "info"),
        (3, 29, "Reserved", "20000000", "info"),
        (3, 30, "Brake input shorted to ground", "40000000", "fault"),
        (3, 31, "Brake input open or shorted to 5V", "80000000", "fault"),
    ]
    return [
        {
            "can_byte": byte,
            "can_bit": bit,
            "bit_number": bit,
            "name": name,
            "fault_word_value": value,
            "severity": severity,
        }
        for byte, bit, name, value, severity in rows
    ]


def run_fault_bits() -> list[dict]:
    rows = [
        (4, 32, "Motor Over-speed", "00000001", "fault"),
        (4, 33, "Over-current detected by software on motor phase", "00000002", "fault"),
        (4, 34, "DC Bus Over-voltage above the software defined limit for the inverter", "00000004", "fault"),
        (4, 35, "Inverter Over-temperature (any module, GDB, or PCB sensor)", "00000008", "fault"),
        (4, 36, "Accelerator Input shorted to ground", "00000010", "fault"),
        (4, 37, "Accelerator Input open or shorted to 5V", "00000020", "fault"),
        (4, 38, "Direction Command Fault", "00000040", "fault"),
        (4, 39, "Inverter Response Time-out", "00000080", "fault"),
        (5, 40, "Hardware Gate/Desaturation Fault", "00000100", "fault"),
        (5, 41, "Hardware Over-current", "00000200", "fault"),
        (5, 42, "DC Bus Under-voltage", "00000400", "fault"),
        (5, 43, "CAN Command Message Lost", "00000800", "fault"),
        (5, 44, "Motor Over-temperature", "00001000", "fault"),
        (5, 45, "Reserved", "00002000", "info"),
        (5, 46, "Reserved", "00004000", "info"),
        (5, 47, "Reserved", "00008000", "info"),
        (6, 48, "Brake Input shorted to ground", "00010000", "fault"),
        (6, 49, "Brake Input open or shorted to 5V", "00020000", "fault"),
        (6, 50, "Module A Over-temperature", "00040000", "fault", "Gen 2 inverters do not have this fault."),
        (6, 51, "Module B Over-temperature", "00080000", "fault", "Gen 2 inverters do not have this fault."),
        (6, 52, "Module C Over-temperature", "00100000", "fault", "Gen 2 inverters do not have this fault."),
        (6, 53, "PCB Over-temperature", "00200000", "fault", "Not available on Gen 2 inverters (Appendix N)."),
        (6, 54, "Gate Drive Board 1 Over-temperature", "00400000", "fault", "Not available on Gen 2 inverters (Appendix N)."),
        (6, 55, "Gate Drive Board 2 Over-temperature", "00800000", "fault", "Gen 2 boards do not have this fault."),
        (7, 56, "Gate Drive Board 3 Over-temperature", "01000000", "fault", "Gen 2 boards do not have this fault."),
        (7, 57, "Current Sensor Fault", "02000000", "fault"),
        (7, 58, "Reserved", "04000000", "info"),
        (7, 59, "Reserved", "08000000", "info"),
        (7, 60, "Hardware based DC Bus over-voltage", "10000000", "fault"),
        (7, 61, "Reserved", "20000000", "info"),
        (7, 62, "Resolver Not Connected", "40000000", "fault"),
        (7, 63, "Inverter Discharge Active", "80000000", "warning"),
    ]
    out = []
    for row in rows:
        item = {
            "can_byte": row[0],
            "can_bit": row[1],
            "bit_number": row[1],
            "name": row[2],
            "fault_word_value": row[3],
            "severity": row[4],
        }
        if len(row) > 5:
            item["notes"] = row[5]
        out.append(item)
    return out


POST_DIAG = [
    ("Hardware Gate/Desaturation Fault", 5, "Hardware de-saturation; cannot clear via Clear Fault Command; recycle power.", "latching"),
    ("HW Over-current Fault", 5, "Any current sensor over-current (six faults ORed).", None),
    ("Accelerator Shorted", 4, "Below Pedal_Lo_EEPROM_(V)_x_100.", None),
    ("Accelerator Open", 4, "Above Pedal_Hi_EEPROM_(V)_x_100.", None),
    ("Current Sensor Low", 3, "Below hard-coded -22.5 A.", None),
    ("Current Sensor High", 3, "Above hard-coded 22.5 A.", None),
    ("Module Temperature Low", 1, "Currently not active.", None),
    ("Module Temperature High", 1, "One or more module temperatures above 125 C.", None),
    ("Control PCB Temperature Low", 1, "Below -24 C.", None),
    ("Control PCB Temperature High", 1, "Exceeded 125 C.", None),
    ("Gate Drive PCB Temperature Low", 1, "Below -24 C.", None),
    ("Gate Drive PCB Temperature High", 1, "Exceeded 125 C.", None),
    ("5V Sense Voltage Low", 2, "5V sense reading too low.", None),
    ("5V Sense Voltage High", 2, "5V sense reading too high.", None),
    ("12V Sense Voltage Low", 2, "12V sense reading too low.", None),
    ("12V Sense Voltage High", 2, "12V sense reading too high.", None),
    ("2.5V Sense Voltage Low", 2, "2.5V sense reading too low.", None),
    ("2.5V Sense Voltage High", 2, "2.5V sense reading too high.", None),
    ("1.5V Sense Voltage Low", 2, "1.5V sense reading too low.", None),
    ("1.5V Sense Voltage High", 2, "1.5V sense reading too high.", None),
    ("DC Bus Voltage High", 6, "During pre-charge above hard-coded SW over-voltage limit.", None),
    ("DC Bus Voltage Low", 6, "DC bus below 100 V.", None),
    ("Pre-charge Timeout", 6, "Not charging at 2.7 V/50 ms and 3 s elapsed.", None),
    ("Pre-charge Voltage Failure", 6, "After pre-charge, DC voltage changed >10 V within 15 ms.", None),
    ("EEPROM Checksum Invalid", 7, "EEPROM checksum not valid.", None),
    ("EEPROM Data Out of Range", 7, "Currently not active.", None),
    ("EEPROM Update Required", 7, "EEPROM parameter count changed; review new parameters.", "not_cleared_by_clear_faults"),
    ("Brake Shorted", 8, "Below Brake_Lo_EEPROM_(V)_x_100.", None),
    ("Brake Open", 8, "Above Brake_Hi_EEPROM_(V)_x_100.", None),
]

RUN_DIAG = [
    ("Motor Over-speed Fault", 6, "Above Motor_Overspeed_EEPROM_(RPM).", None),
    ("Over-current Fault", 3, "Phase current above hard-coded SW over-current limit.", None),
    ("Over-voltage Fault", 2, "Filtered DC above hard-coded SW over-voltage limit.", None),
    ("Inverter Over-temperature Fault", 1, "Module temp above Inv_OverTemp_Limit_EEPROM_(C)_x_10.", None),
    ("Accelerator Input Shorted Fault", 4, "Below Pedal_Lo_EEPROM_(V)_x_100.", None),
    ("Accelerator Input Open Fault", 4, "Above Pedal_Hi_EEPROM_(V)_x_100.", None),
    ("Direction Command Fault", 7, "Both forward and reverse active; fault has been de-activated.", None),
    ("Inverter Response Time-out Fault", 8, "Inverter not enabled within 2 minutes of enable command.", None),
    ("Hardware Gate/Desaturation Fault", 5, "Hardware de-saturation; cannot clear via Clear Fault Command; recycle power.", "latching"),
    ("Hardware Over-current Fault", 5, "Any current sensor over-current (six faults ORed).", None),
    ("Under-voltage Fault", 2, "Below DC_UnderVolt_Thresh_EEPROM_(V)_x_10.", None),
    ("CAN Command Message Lost Fault", 9, "Heartbeat command message not seen in CAN mode.", None),
    ("Motor Over-temperature Fault", 1, "Above Mtr_OverTemp_Limit_EEPROM_(C)_x_10.", None),
    ("Brake Input Shorted Fault", 10, "Below Brake_Lo_EEPROM_(V)_x_100.", None),
    ("Brake Input Open Fault", 10, "Above Brake_Hi_EEPROM_(V)_x_100.", None),
    ("Module A Over-temperature Fault", 1, "Above Inv_OverTemp_Limit_EEPROM_(C)_x_10; not on Gen 2.", None),
    ("Module B Over-temperature Fault", 1, "Above Inv_OverTemp_Limit_EEPROM_(C)_x_10; not on Gen 2.", None),
    ("Module C Over-temperature Fault", 1, "Above Inv_OverTemp_Limit_EEPROM_(C)_x_10; not on Gen 2.", None),
    ("PCB Over-temperature Fault", 1, "Above Inv_OverTemp_Limit_EEPROM_(C)_x_10; not on Gen 2.", None),
    ("Gate Drive Board 1 Over-temperature Fault", 1, "Above Inv_OverTemp_Limit_EEPROM_(C)_x_10; not on Gen 2.", None),
    ("Gate Drive Board 2 Over-temperature Fault", 1, "Above Inv_OverTemp_Limit_EEPROM_(C)_x_10; Gen 2 boards do not have this fault.", None),
    ("Gate Drive Board 3 Over-temperature Fault", 1, "Above Inv_OverTemp_Limit_EEPROM_(C)_x_10; Gen 2 boards do not have this fault.", None),
    ("Current Sensor Fault", 3, "Current readings out of range; sensor assumed malfunctioning.", None),
    ("Resolver Not Connected Fault", 11, "Resolver not connected.", None),
    ("Inverter Discharge Active", 11, "Inverter discharge in process.", "warning"),
]


def build_faults() -> dict:
    post_bits = post_fault_bits()
    run_bits = run_fault_bits()
    return {
        "manual_version": MANUAL_VERSION,
        "source_pdf": SOURCE_PDF,
        "pages": [32, 33, 37, 38, 76, 77, 78, 79, 80],
        "reporting": {
            "transport": "Fault bits mapped to CAN bytes 0–7 in a fault word; CAN message ID not specified in this manual.",
            "legacy_symbols_removed": ["post_fault_hi", "post_fault_lo", "run_fault_hi", "run_fault_lo"],
            "gui_access": "Check Faults button on RMS GUI Memory View page.",
            "clear_command": {
                "name": "Clear Faults Command",
                "value_to_clear": 0,
                "clears": "All active faults including POST faults except EEPROM Update Required.",
                "can_mode_note": "Inverter must be disabled before sending Clear Faults Command in CAN mode.",
            },
            "fault_indicator_priority": "POST faults (higher) then RUN faults (lower); POST followed by two quick blinks.",
        },
        "registers": [
            {
                "name": "POST_Fault_Word",
                "can_bytes": [0, 1, 2, 3],
                "bits": post_bits,
                "diagnostics": [
                    {
                        "name": name,
                        "fault_indicator_blinks": blinks,
                        "description": desc,
                        **({"clear_behavior": clear} if clear else {}),
                    }
                    for name, blinks, desc, clear in POST_DIAG
                ],
            },
            {
                "name": "RUN_Fault_Word",
                "can_bytes": [4, 5, 6, 7],
                "bits": run_bits,
                "diagnostics": [
                    {
                        "name": name,
                        "fault_indicator_blinks": blinks,
                        "description": desc,
                        **({"clear_behavior": clear} if clear else {}),
                    }
                    for name, blinks, desc, clear in RUN_DIAG
                ],
            },
        ],
        "warnings_distinct": [
            {"name": "EEPROM Update Required", "register": "POST_Fault_Word", "bit": 26},
            {"name": "Inverter Discharge Active", "register": "RUN_Fault_Word", "bit": 63},
        ],
        "undocumented_in_bit_tables": [
            {
                "name": "FWD_RVS_INVALID_STATE_FAULT",
                "notes": "Declared in Wait State when both /FORWARD and /REVERSE active; not mapped to fault word in this manual.",
            }
        ],
    }


SCI_BROADCAST = [
    (1, "Power_On_Timer_Lo", "The low word of the Power On Timer (increments every 3 ms)", None, 1, None),
    (2, "Filtered_Accel_Pot", "Filtered Accel-pot input voltage (V) times 100", "V", 100, None),
    (3, "Motor_Torque_Feedback", "Motor Torque feedback (Nm) times 10", "N.m", 10, None),
    (4, "Vehicle_Torque_Command", "Vehicle Torque Command (Nm) times 10", "N.m", 10, None),
    (5, "DC_Voltage", "DC Voltage (V) times 10", "V", 10, None),
    (6, "DC_Current", "DC Current (A) times 10", "A", 10, None),
    (7, "Motor_Speed", "Motor Speed (rpm)", "rpm", 1, None),
    (8, "Flux_Weakening_Regulator_Output", "Flux Weakening Regulator Output (Apk) times 10", "Apk", 10, None),
    (9, "Motor_Voltage_Magnitude", "Motor Voltage Magnitude (Vpk) times 10", "Vpk", 10, None),
    (10, "IQ_Command", "IQ Command (Apk) times 10", "Apk", 10, None),
    (11, "IQ_Feedback", "IQ Feedback (Apk) times 10", "Apk", 10, None),
    (12, "ID_Command", "ID Command (Apk) times 10", "Apk", 10, None),
    (13, "ID_Feedback", "ID Feedback (Apk) times 10", "Apk", 10, None),
    (14, "Modulation", "Modulation times 10000", None, 10000, None),
    (15, "Module_A_Temperature", "Module A Temperature (°C) times 10", "°C", 10, None),
    (16, "Motor_Temperature", "Motor Temperature (°C) times 10", "°C", 10, None),
    (17, "Run_Fault_Lo_Word", "Run Fault Low Word", None, 1, None),
    (18, "Run_Fault_Hi_Word", "Run Fault High Word", None, 1, None),
    (19, "Torque_Shudder", "Torque Shudder (Nm) times 10", "N.m", 10, None),
    (20, "Filtered_Brake_Pot", "Filtered Brake pot (V) times 100", "V", 100, None),
]

GUI_MONITORED = [
    ("Run_Command(Trq=0_Spd=1)", "Current command mode (Torque=0 / Speed=1).", None, 1, {"0": "Torque", "1": "Speed"}),
    ("Commanded_Speed_(RPM)", "Commanded speed in Speed mode.", "rpm", 1, None),
    ("Feedback_Speed_(RPM)", "Motor speed from position feedback sensor.", "rpm", 1, None),
    ("Commanded_Torque_(Nm)_x_10", "Commanded torque in torque mode.", "N.m", 10, None),
    ("Feedback_Torque_(Nm)_x_10", "Calculated motor torque from currents and motor parameters.", "N.m", 10, None),
    ("Voltage_Feedback_Speed_(RPM)", "Speed from back EMF; valid when sufficient EMF and motor not enabled.", "rpm", 1, None),
    ("Torque_Shudder_(Nm)_x_10", "Shudder compensation torque.", "N.m", 10, None),
    ("V_DC_Filtered_(Volts)_x_10", "DC Bus Voltage.", "V", 10, None),
    ("V_MAG_Filtered_(Volts)_x_10", "Motor output voltage magnitude (line-to-neutral peak).", "Vpk", 10, None),
    ("SW_Over_Voltage_(Volts)_x_10", "Hard-coded over-voltage threshold.", "V", 10, None),
    ("I_DC_Filtered_(Amps)_x_10", "Estimated DC bus current.", "A", 10, None),
    ("I_MAG_Filtered_(Amps)_x_10", "Motor phase current magnitude (peak, not RMS).", "Apk", 10, None),
    ("SW_Over_Current_(Amps)_x_10", "Hard-coded over-current threshold.", "A", 10, None),
    ("Motor_Temp_(C)_x_10", "Motor temperature if sensor available.", "°C", 10, None),
    ("Mod_A_Temp_(C)_x_10", "Phase A power module temperature.", "°C", 10, None),
    ("Mod_B_Temp_(C)_x_10", "Phase B power module temperature.", "°C", 10, None),
    ("Mod_C_Temp_(C)_x_10", "Phase C power module temperature.", "°C", 10, None),
    ("PCB_Temp_(C)_x_10", "Control board PCB temperature.", "°C", 10, None),
    ("GDB_Temp_(C)_x_10", "Gate driver board PCB temperature (Gen-2 only).", "°C", 10, None),
    ("GDB_1_Temp_(C)_x_10", "Gate driver board 1 temperature (non Gen-2).", "°C", 10, None),
    ("GDB_2_Temp_(C)_x_10", "Gate driver board 2 temperature (non Gen-2).", "°C", 10, None),
    ("GDB_3_Temp_(C)_x_10", "Gate driver board 3 temperature (non Gen-2).", "°C", 10, None),
    ("RTD1_Temp_(C)_x_10", "RTD1 input temperature.", "°C", 10, None),
    ("RTD2_Temp_(C)_x_10", "RTD2 input temperature.", "°C", 10, None),
    ("RTD3_Temp_(C)_x_10", "RTD3 input temperature (Gen-2 only).", "°C", 10, None),
    ("RTD4_Temp_(C)_x_10", "RTD4 input temperature (Gen-2 only).", "°C", 10, None),
    ("RTD5_Temp_(C)_x_10", "RTD5 input temperature (Gen-2 only).", "°C", 10, None),
    ("ID_Bits", "Hardware ID: 3=Gen-2/RM/CM200, 2=Gen-3/Gen5.", None, 1, {"2": "Gen-3/Gen5", "3": "Gen-2/RM/CM200"}),
    ("Inverter_Mode", "Inverter state (inv_mode); see vsm_states.yaml inverter_states.", None, 1, None),
    ("VSM_State", "Vehicle state machine state.", None, 1, None),
    ("Inverter_Enable", "1 when inverter enabled, 0 when disabled.", None, 1, {"0": "Disabled", "1": "Enabled"}),
    ("Vehicle_Direction", "Commanded direction: 1=Forward, 0=Not commanded, -1=Reverse.", None, 1, {"-1": "Reverse", "0": "Not commanded", "1": "Forward"}),
    ("Ignition_Input", "DIN5 state.", None, 1, {"0": "Deasserted", "1": "Asserted"}),
    ("Start_Input", "DIN6 state.", None, 1, {"0": "Deasserted", "1": "Asserted"}),
    ("Brake_Switch", "DIN3 state.", None, 1, {"0": "Deasserted", "1": "Asserted"}),
    ("Forward_Switch", "DIN1 state.", None, 1, {"0": "Deasserted", "1": "Asserted"}),
    ("Reverse_Switch", "DIN2 state.", None, 1, {"0": "Deasserted", "1": "Asserted"}),
    ("Regen_Disable_Switch", "DIN4 state.", None, 1, {"0": "Deasserted", "1": "Asserted"}),
    ("OK_Output_Status", "RLY3 state.", None, 1, {"0": "Deasserted", "1": "Asserted"}),
    ("Precharge_Output_Status", "RLY1 state.", None, 1, {"0": "Deasserted", "1": "Asserted"}),
    ("Main_Output_Status", "RLY2 state.", None, 1, {"0": "Deasserted", "1": "Asserted"}),
    ("Fault_Output_Status", "RLY4 state.", None, 1, {"0": "Deasserted", "1": "Asserted"}),
    ("Hall_Input_1_Status", "Hall Input 1 status.", None, 1, None),
    ("Hall_Input_2_Status", "Hall Input 2 status.", None, 1, None),
    ("Hall_Input_3_Status", "Hall Input 3 status.", None, 1, None),
    ("Encoder_Input_A_Status", "Encoder Input A status.", None, 1, None),
    ("Encoder_Input_B_Status", "Encoder Input B status.", None, 1, None),
    ("Encoder_Input_Z_Status", "Encoder Input Z status.", None, 1, None),
    ("SAT_Fault_Output_Status", "HW Desaturation fault output: 0=asserted, 1=deasserted.", None, 1, None),
    ("OC_Fault_Output_Status", "HW Over-current fault output: 0=asserted, 1=deasserted.", None, 1, None),
    ("VSM_Accel_Filtered", "Voltage on AIN1; 0=0 V, 500=5.0 V.", "V", 100, None),
    ("VSM_Brake_Filtered", "Voltage on AIN3; 0=0 V, 500=5.0 V.", "V", 100, None),
    ("Power_on_Timer_3ms_(Hi_byte)", "Upper 16 bits of 32-bit power-on timer (3 ms intervals).", None, 1, None),
    ("Power_on_Timer_3ms_(Lo_byte)", "Lower 16 bits of 32-bit power-on timer.", None, 1, None),
    ("Sin_corr_(V)_x_100", "Resolver SIN input peak (Gen 2 and Gen 3).", "V", 100, None),
    ("Cos_corr_(V)_x_100", "Resolver COS input peak (Gen 2 and Gen 3).", "V", 100, None),
    ("Motor_Angle_(DEG)_x_10", "Motor shaft rotational position.", "deg", 10, None),
    ("Delta_Resolver_In_Fil_(DEG)_x_10", "Offset between back EMF angle and resolver angle (motor not enabled).", "deg", 10, None),
]

EEPROM_COMMAND = [
    ("Inv_Cmd_Mode_EEPROM", "0x011B", "0 or 1", "0=CAN bus control; 1=VSM mode (accelerator/switches)."),
    ("Discharge_Enable_EEPROM", "0x016D", "0, 1, 2", "0=disabled; 1=enabled without faults; 2=enabled with faults."),
    ("Clear Faults Command", None, "0", "Set to 0 to clear faults (symbol name only; GUI address not in this manual)."),
]


def build_can_signals() -> dict:
    sci_msg = {
        "name": "SCI_Broadcast_Records",
        "transport": "RS232 SCI",
        "direction": "status",
        "can_id_hex": None,
        "can_id_decimal": None,
        "endianness": None,
        "cycle_time_ms": None,
        "pages": [18, 19],
        "notes": [
            "57600 baud, 8N1, no flow control.",
            "Each record is 16-bit; four ASCII nibbles plus space; CRLF after full set.",
            "Update rate depends on record count and processor availability.",
        ],
        "signals": [
            {
                "name": name,
                "sci_record": rec,
                "description": desc,
                "unit": unit,
                "multiplier": mult,
                "raw_to_physical": f"physical = raw / {mult}" if mult and mult != 1 else "physical = raw",
            }
            for rec, name, desc, unit, mult, _ in SCI_BROADCAST
        ],
    }

    fault_msg = {
        "name": "Fault_Word",
        "transport": "CAN",
        "direction": "status",
        "can_id_hex": None,
        "can_id_decimal": None,
        "endianness": None,
        "cycle_time_ms": None,
        "pages": [33, 37, 38],
        "notes": [
            "Manual maps POST faults to CAN bytes 0–3 and RUN faults to bytes 4–7.",
            "CAN message ID, start bit layout, and endianness not specified in this manual; see separate CAN Protocol document.",
        ],
        "signals": [
            {
                "name": bit["name"],
                "can_byte": bit["can_byte"],
                "can_bit": bit["can_bit"],
                "bit_number": bit["bit_number"],
                "length_bits": 1,
                "severity": bit["severity"],
                "fault_word_value": bit["fault_word_value"],
            }
            for reg in build_faults()["registers"]
            for bit in reg["bits"]
        ],
    }

    gui_msg = {
        "name": "GUI_Monitored_Parameters",
        "transport": "RS232 RMS GUI Memory View",
        "direction": "status",
        "can_id_hex": None,
        "can_id_decimal": None,
        "pages": [72, 73, 74],
        "signals": [
            {
                "name": name,
                "description": desc,
                "unit": unit,
                "multiplier": mult,
                **({"enum": enum} if enum else {}),
            }
            for name, desc, unit, mult, enum in GUI_MONITORED
        ],
    }

    cmd_msg = {
        "name": "EEPROM_Parameter_Message",
        "transport": "CAN",
        "direction": "command",
        "can_id_hex": None,
        "can_id_decimal": None,
        "pages": [25, 47],
        "notes": [
            "EEPROM parameters may be programmed via RMS GUI or CAN Parameter message.",
            "Appendix C defers all CAN configuration to separate CAN Protocol document.",
        ],
        "signals": [
            {
                "name": name,
                **({"gui_address": addr} if addr else {}),
                "value_range": rng,
                "description": desc,
            }
            for name, addr, rng, desc in EEPROM_COMMAND
        ],
    }

    data_formats = {
        "Temperature": {"variable_type": "Signed Integer", "range": "±3000.0", "unit": "°C", "multiplier": 10},
        "Low Voltage": {"variable_type": "Signed Integer", "range": "±300.00", "unit": "Volts", "multiplier": 100},
        "High Voltage": {"variable_type": "Signed Integer", "range": "±3000.0", "unit": "Volts", "multiplier": 10},
        "Torque": {"variable_type": "Signed Integer", "range": "±3000.0", "unit": "N.m.", "multiplier": 10},
        "Current": {"variable_type": "Signed Integer", "range": "±3000.0", "unit": "Amps", "multiplier": 10},
        "Angle": {"variable_type": "Signed Integer", "range": "0 to ±359.9", "unit": "Degrees", "multiplier": 10},
        "Angular Velocity": {"variable_type": "Signed Integer", "range": "±30000", "unit": "RPM", "multiplier": 1},
    }

    return {
        "manual_version": MANUAL_VERSION,
        "source_pdf": SOURCE_PDF,
        "pages": [18, 19, 20, 33, 37, 38, 47, 72, 73, 74],
        "protocol_gaps": [
            "CAN message IDs, broadcast cycle times, and signal start-bit layouts are not in this manual.",
            "Refer to external document: CAN Protocol.",
            "Appendix C (CAN Configuration Parameters) contains no parameter table in revision 3.6.",
        ],
        "data_formats": data_formats,
        "messages": [fault_msg, sci_msg, gui_msg, cmd_msg],
    }


GRAPH_CANDIDATES = [
    ("Feedback_Speed_(RPM)", "rpm", "Motor speed from feedback sensor.", None, None, [72]),
    ("Commanded_Speed_(RPM)", "rpm", "Commanded speed in speed mode.", None, None, [72]),
    ("Feedback_Torque_(Nm)_x_10", "N.m", "Calculated motor torque.", None, None, [72]),
    ("Commanded_Torque_(Nm)_x_10", "N.m", "Commanded torque.", None, None, [72]),
    ("V_DC_Filtered_(Volts)_x_10", "V", "DC bus voltage.", "±3000.0", 10, [72]),
    ("I_DC_Filtered_(Amps)_x_10", "A", "Estimated DC bus current.", "±3000.0", 10, [72]),
    ("I_MAG_Filtered_(Amps)_x_10", "Apk", "Phase current magnitude (peak).", "±3000.0", 10, [72]),
    ("Motor_Temp_(C)_x_10", "°C", "Motor temperature.", "±3000.0", 10, [73]),
    ("Mod_A_Temp_(C)_x_10", "°C", "Module A temperature.", "±3000.0", 10, [73]),
    ("Mod_B_Temp_(C)_x_10", "°C", "Module B temperature.", "±3000.0", 10, [73]),
    ("Mod_C_Temp_(C)_x_10", "°C", "Module C temperature.", "±3000.0", 10, [73]),
    ("PCB_Temp_(C)_x_10", "°C", "Control PCB temperature.", "±3000.0", 10, [73]),
    ("VSM_Accel_Filtered", "V", "Accelerator input voltage.", "0–5", 100, [74]),
    ("VSM_Brake_Filtered", "V", "Brake input voltage.", "0–5", 100, [74]),
    ("Motor_Torque_Feedback", "N.m", "SCI broadcast torque feedback.", "±3000.0", 10, [19]),
    ("DC_Voltage", "V", "SCI broadcast DC voltage.", "±3000.0", 10, [19]),
    ("DC_Current", "A", "SCI broadcast DC current.", "±3000.0", 10, [19]),
    ("Motor_Speed", "rpm", "SCI broadcast motor speed.", "±30000", 1, [19]),
    ("IQ_Feedback", "Apk", "Q-axis current feedback.", "±3000.0", 10, [19]),
    ("ID_Feedback", "Apk", "D-axis current feedback.", "±3000.0", 10, [19]),
    ("Modulation", None, "Inverter modulation index.", None, 10000, [19]),
]


def build_graph_candidates() -> dict:
    return {
        "manual_version": MANUAL_VERSION,
        "source_pdf": SOURCE_PDF,
        "pages": [19, 20, 72, 73, 74],
        "candidates": [
            {
                "signal": sig,
                "unit": unit,
                "description": desc,
                "typical_range": {
                    "manual_format_range": fmt_range,
                    "multiplier": mult,
                }
                if fmt_range
                else None,
                "pages": pages,
            }
            for sig, unit, desc, fmt_range, mult, pages in GRAPH_CANDIDATES
        ],
    }


def write_notes() -> None:
    text = """# PDF Extract Notes — Cascadia Motion Software User Manual V3.6

**Source:** `/Users/rrxie/Downloads/Software User Manual (V3_6) For Inverter.pdf`  
**Revision:** 3.6 (1/14/2021)  
**Publisher:** Cascadia Motion (formerly Rinehart Motion Systems)

## Protocol version

- Manual revision **3.6**; firmware/GUI versioning is per Firmware Release Package (SWRP), not a single CAN protocol version in this document.

## Default bitrates / transports

| Transport | Settings | Pages |
|-----------|----------|-------|
| RS232 SCI data acquisition | 57600 baud, 8 data bits, no parity, 1 stop bit, no flow control | 18 |
| RS232 RMS GUI | COM port auto-configured by GUI; no manual baud setup required | 22 |
| RS232 C2PROG firmware programming | 57600 baud, 8N1 | 14 |
| CAN | **Not specified in this manual.** Appendix C refers to separate **CAN Protocol** document. | 47 |

## How faults are reported

- **Fault word:** POST faults occupy CAN bytes **0–3** (bits 0–31); RUN faults occupy bytes **4–7** (bits 32–63). Bit maps on pages 33, 37–38.
- **Legacy symbols removed:** `post_fault_hi`, `post_fault_lo`, `run_fault_hi`, `run_fault_lo`.
- **GUI:** Memory View → Check Faults button; Clear Faults sets Clear Faults Command to **0**.
- **Fault indicator:** Blinks one fault; POST priority over RUN; POST followed by two quick blinks. Blink count maps to fault (Appendices M/N).
- **Warnings (distinct):** EEPROM Update Required (POST bit 26); Inverter Discharge Active (RUN bit 63).
- **Latching:** Hardware Gate/Desaturation (POST & RUN) requires power recycle; EEPROM Update Required not cleared by Clear Faults.

## EEPROM / parameter flashing feasibility

- EEPROM parameters programmable via **RMS GUI** (RS232) or **CAN Parameter message** (details in CAN Protocol doc, not this manual).
- After firmware reflash: **EEPROM Update Required** warning; user must accept/update parameters.
- After EEPROM programming: VSM enters **Recycle Power State (15)**; controller must be re-powered.
- GUI can save/load EEPROM value files; Program EEPROM command writes to non-volatile memory.

## Key section page index

| Topic | Pages |
|-------|-------|
| SCI broadcast parameters | 18–19 |
| Data format multipliers | 20 |
| RMS GUI / EEPROM guide | 22–24 |
| Vehicle State Machine | 31–39 |
| POST fault bit table | 33 |
| RUN fault bit table | 37–38 |
| Appendix C CAN config | 47 (empty — external doc) |
| GUI monitored parameters | 72–74 |
| POST fault diagnostics | 76–77 |
| RUN fault diagnostics | 78–80 |

## Ambiguous / missing from this manual

1. **CAN message IDs**, broadcast cycle times, endianness, and per-signal start bits — deferred to **CAN Protocol** document.
2. **Appendix C** contains no parameter table (only a reference to CAN Protocol).
3. **Section 11 / 11.4** referenced for VSM_State and Inverter_Mode but not present in revision 3.6 TOC.
4. **FWD_RVS_INVALID_STATE_FAULT** named in Wait State text but not mapped to fault word bits.
5. **Clear Faults Command** GUI/CAN address not listed (behavior only).
6. **Heartbeat command message** referenced for CAN mode fault 43; message ID/format not in this manual.
7. VSM state IDs **8–13** and inverter state IDs **13–14** are undefined gaps in numbering.
8. Run fault table Module A bit value shows `00400000` on page 37 for bit 50 — verify against hardware revision; adjacent bits use sequential hex masks.

## Recommended follow-up documents

- CAN Protocol (Cascadia Motion)
- Inverter Discharge Process Manual
- Motor-specific setup manuals (Motor_Type_EEPROM)
- Firmware Release Package default symbols file (`defsyms_yyyymmdd.txt`)
"""
    (DOCS / "pdf-extract-notes.md").write_text(text, encoding="utf-8")


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)
    dump(DATA / "vsm_states.yaml", build_vsm_states())
    dump(DATA / "faults.yaml", build_faults())
    dump(DATA / "can_signals.yaml", build_can_signals())
    dump(DATA / "graph_candidates.yaml", build_graph_candidates())
    write_notes()


if __name__ == "__main__":
    main()
