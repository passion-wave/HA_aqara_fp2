# Third-party notices

Aqara Presence Lab independently implements the protocol described in the supplied specification. It does not vendor the SleepRadar poller.

The login contract, password preparation, signing format and two public manufacturer constants in `custom_components/aqara_presence_lab/api/protocol_constants.py` were checked against **SleepRadar**, copyright (c) 2026 Florian Horner, distributed under the MIT License. Its full license is reproduced in [docs/licenses/SleepRadar-MIT.txt](docs/licenses/SleepRadar-MIT.txt).

Source file: `aqara_fp2_sleep/aqara_fp2_sleep_poller.py` in `florianhorner/ha-fp2-sleep`.

- Source blob: `b48a4417deebd04cf4e6b3eb3d918300e6081d25`
- Commit containing that exact blob: `3af017fc995d5f05e65720ae5b1ed0690a04504c`
- License blob in the same commit: `cb25bb7cf32705faf3cccbafa1948d57c7e05818`
- [Pinned source](https://github.com/florianhorner/ha-fp2-sleep/blob/3af017fc995d5f05e65720ae5b1ed0690a04504c/aqara_fp2_sleep/aqara_fp2_sleep_poller.py)
- [Pinned license](https://github.com/florianhorner/ha-fp2-sleep/blob/3af017fc995d5f05e65720ae5b1ed0690a04504c/LICENSE)

The constants are not personal account credentials, but are intentionally excluded from diagnostics. The original resource endpoint differs from this project's qlink endpoint. Neither these constants nor synthetic signature tests establish live compatibility.
