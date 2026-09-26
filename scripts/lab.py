#!/usr/bin/env python3
"""Local capture importer and opt-in single probe; never a polling daemon."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

# Import the same packaged API without importing Home Assistant's integration.
# A standalone namespace alias leaves relative API imports intact.
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType("aqara_lab_api")
package.__path__ = [str(ROOT / "custom_components/aqara_presence_lab/api")]
sys.modules.setdefault("aqara_lab_api", package)

from aqara_lab_api.auth import SessionAuthProvider  # noqa: E402
from aqara_lab_api.client import AsyncAqaraClient  # noqa: E402
from aqara_lab_api.errors import AqaraError, ProtocolUnsupported  # noqa: E402
from aqara_lab_api.importers import (  # noqa: E402
    MAX_IMPORT_BYTES,
    import_curl,
    import_har,
    import_package,
)
from aqara_lab_api.parsing import parse_response  # noqa: E402
from aqara_lab_api.profiles import PROFILE  # noqa: E402
from aqara_lab_api.signing import CandidateSigner  # noqa: E402
from aqara_lab_api.validation import (  # noqa: E402
    ProbeBudget,
    probe_report,
    signature_matches,
    signature_report,
)


def read_private(path: Path) -> bytes:
    # Limit before reading; don't echo paths or input data in errors.
    with path.open("rb") as handle:
        data = handle.read(MAX_IMPORT_BYTES + 1)
    if len(data) > MAX_IMPORT_BYTES:
        raise ProtocolUnsupported()
    return data


def write_package(path: Path, capture) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(capture.package(), handle, ensure_ascii=False, indent=2)


async def run_probe(capture, signer, *, allow_live: bool, state: Path, step: str) -> dict:
    if not allow_live or not signature_matches(capture, signer):
        raise ProtocolUnsupported()
    budget = ProbeBudget(state)
    budget.reserve(capture.credentials.user_id, step=step)
    import aiohttp

    async with aiohttp.ClientSession(
        trust_env=False, cookie_jar=aiohttp.DummyCookieJar()
    ) as session:
        client = AsyncAqaraClient(session, SessionAuthProvider(capture.credentials), signer)
        try:
            snapshot = await client.async_probe_capture(capture, consent=True)
            report = probe_report(snapshot)
            report["gate"] = step
            return report
        finally:
            budget.defer(capture.credentials.user_id, client.limiter.retry_after, step=step)
            await client.async_close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    preview = commands.add_parser("offline", help="Validate a local response; no network")
    preview.add_argument("file", type=Path)
    importer = commands.add_parser("import", help="Parse a local export; no shell/network")
    importer.add_argument("format", choices=("har", "curl", "package"))
    importer.add_argument("file", type=Path)
    importer.add_argument("--output", type=Path, required=True)
    importer.add_argument("--entry-index", type=int)
    signature = commands.add_parser("signature", help="G1 comparison only; no network")
    signature.add_argument("file", type=Path)
    probe = commands.add_parser("probe", help="G1 + one fresh signed G2/G3 read")
    probe.add_argument("file", type=Path)
    probe.add_argument(
        "--allow-live", action="store_true", help="Explicitly authorize one Aqara request"
    )
    probe.add_argument("--step", choices=("G2", "G3"), default="G2")
    probe.add_argument("--state", type=Path, default=ROOT / "private/probe-budget.json")
    args = parser.parse_args(argv)
    try:
        if args.command == "offline":
            report = probe_report(parse_response(read_private(args.file)))
            report.update(gate="G0", network_requests=0, result="offline_schema_validated")
        elif args.command == "import":
            data = read_private(args.file)
            if args.format == "har":
                capture = import_har(data, entry_index=args.entry_index)
            else:
                capture = {"curl": import_curl, "package": import_package}[args.format](data)
            write_package(args.output, capture)
            report = capture.preview()
        else:
            capture = import_package(read_private(args.file))
            signer = CandidateSigner(PROFILE.app_key, PROFILE.app_id)
            if args.command == "signature":
                report = signature_report(capture, signer)
            else:
                report = asyncio.run(
                    run_probe(
                        capture,
                        signer,
                        allow_live=args.allow_live,
                        state=args.state,
                        step=args.step,
                    )
                )
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 1 if report.get("result") in ("not_matched", "no_selected_device_data") else 0
    except AqaraError as error:
        print(
            json.dumps({"result": "failed", "error": error.error_key, "production_allowed": False})
        )
        return 1
    except OSError, ValueError, TypeError, KeyError:
        print(
            json.dumps(
                {"result": "failed", "error": "invalid_local_file", "production_allowed": False}
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
