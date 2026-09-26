"""Create a deterministic, runtime-only manual-install ZIP and SHA-256 digest."""

import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "aqara_presence_lab"


def build() -> Path:
    """Package only explicit runtime file types; never captures or credentials."""
    version = json.loads((COMPONENT / "manifest.json").read_text())["version"]
    output = ROOT / "dist" / f"aqara_presence_lab-{version}.zip"
    output.parent.mkdir(exist_ok=True)
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for path in sorted(COMPONENT.rglob("*")):
            if not path.is_file() or path.suffix not in {".py", ".json", ".png", ".yaml", ".txt"}:
                continue
            if any(part.startswith(".") or part == "__pycache__" for part in path.parts):
                continue
            info = ZipInfo(str(path.relative_to(ROOT)), date_time=(2026, 9, 26, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(".zip.sha256").write_text(f"{digest}  {output.name}\n")
    return output


if __name__ == "__main__":
    print(build().relative_to(ROOT))
