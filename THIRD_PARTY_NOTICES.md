# Third-party notices

Aqara Presence Lab independently implements the protocol described in the supplied specification. It does not vendor the SleepRadar poller.

The login contract, password preparation, signing format and two public manufacturer constants in `custom_components/aqara_presence_lab/api/protocol_constants.py` were checked against **SleepRadar**, copyright (c) 2026 Florian Horner, distributed under the MIT License. Its full license is reproduced in [docs/licenses/SleepRadar-MIT.txt](docs/licenses/SleepRadar-MIT.txt).

Source file: `aqara_fp2_sleep/aqara_fp2_sleep_poller.py` in `florianhorner/ha-fp2-sleep`.

- Source blob: `b48a4417deebd04cf4e6b3eb3d918300e6081d25`
- Commit containing that exact blob: `3af017fc995d5f05e65720ae5b1ed0690a04504c`
- License blob in the same commit: `cb25bb7cf32705faf3cccbafa1948d57c7e05818`
- [Pinned source](https://github.com/florianhorner/ha-fp2-sleep/blob/3af017fc995d5f05e65720ae5b1ed0690a04504c/aqara_fp2_sleep/aqara_fp2_sleep_poller.py)
- [Pinned license](https://github.com/florianhorner/ha-fp2-sleep/blob/3af017fc995d5f05e65720ae5b1ed0690a04504c/LICENSE)

The constants are not personal account credentials, but are intentionally excluded from diagnostics. Version 0.3.0b1 also implements the documented read-only resource endpoint, separately from the qlink endpoint. Neither these constants nor synthetic signature tests establish live compatibility.


The supplemental FP2 attribute catalog, numeric/enum presentation metadata and
read-only settings contract were checked against **ha-aqara-devices-V3-Fork**,
copyright (c) 2025 darkdragon, distributed under the MIT License. The parser,
account scheduling and Home Assistant entities are independently implemented;
no upstream default-value fallback or write operation is used.

- Commit: `ca46546673d52ab819b3da5be7d98d4bb33f854a`
- `const.py` blob: `99dd51964f2b4ff9a2dd0b8909c4ed83b2ee1b57`
- `api.py` blob: `f218001550d8a609e09406d64d8b6bbeb91bf12c`
- `fp2.py` blob: `6b31f06c6b224b59abe09dbcf1a18b9236666274`
- License blob: `59c73c42379ac54e7fe29cf8d7d78d137d5da39e`
- [Pinned source tree](https://github.com/Serein-Zhang/ha-aqara-devices-V3-Fork/tree/ca46546673d52ab819b3da5be7d98d4bb33f854a/custom_components/ha_aqara_devices)
- [Pinned license](https://github.com/Serein-Zhang/ha-aqara-devices-V3-Fork/blob/ca46546673d52ab819b3da5be7d98d4bb33f854a/LICENSE)
- [Full license copy](docs/licenses/AqaraDevices-MIT.txt); also included in the runtime ZIP.

Public source mappings describe the protocol candidate. They do not establish
that every field exists on each device, or that a received value is a fresh
physical observation.
