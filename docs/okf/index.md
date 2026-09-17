---
okf_version: "0.2"
---

# PM100DX Inverter Knowledge Bundle

OKF v0.2 bundle for the Cascadia Motion PM100DX inverter as operated by this
repository (`inverter-monitor`, read-only live monitor). Sources are the two
vendor PDFs in `../Source Documentation/` plus the repo's existing decode
tables.

* [CAN bus](./can/index.md) — transport, broadcast catalog, command/parameter messages
* [Inverter behavior](./inverter/index.md) — VSM, inverter mode, faults, serial links
* [Monitor mapping](./monitor/index.md) — how `inverter-monitor` reads (never writes)
