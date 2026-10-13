---
okf_version: "0.2"
---

# PM100 Inverter Knowledge Bundle

OKF v0.2 bundle for Cascadia Motion / Rinehart PM100 series inverters (PM100,
PM100DX, PM100DZ, etc.) as operated by this repository (`inverter-monitor`,
live monitor and configuration tool). Sources are vendor documentation
plus the repo's decode tables and reverse-engineered protocol captures.

* [Inverter behavior](./inverter/index.md) — VSM, inverter mode, faults, serial links, EEPROM map
* [Monitor mapping](./monitor/index.md) — how `inverter-monitor` decodes telemetry, monitors health, and executes guarded writes
