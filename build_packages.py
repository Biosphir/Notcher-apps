"""Build independently downloadable Notcher app packages and a release catalog."""
import argparse
import hashlib
import json
import zipfile
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent


def build(output, tag):
    output.mkdir(parents=True, exist_ok=True)
    catalog = []
    for entry in json.loads((ROOT / "catalog.json").read_text(encoding="utf-8")):
        folder = ROOT / entry["module"]
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        if manifest != entry:
            raise ValueError(f"Catalog and manifest disagree for {entry['id']}")
        filename = f"{entry['id']}-{entry['version']}.notcher-app"
        target = output / filename
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            files = [("manifest.json", json.dumps(entry, indent=2).encode())]
            files += [
                (path.relative_to(ROOT).as_posix(), path.read_bytes())
                for path in sorted(folder.rglob("*"))
                if path.is_file() and "__pycache__" not in path.parts
            ]
            for name, data in files:
                info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, data)
        published = {
            **entry,
            "download_url": f"https://github.com/Biosphir/Notcher-apps/releases/download/{tag}/{filename}",
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "size": target.stat().st_size,
        }
        icon = next((folder / name for name in ("icon.png", "icon.svg") if (folder / name).is_file()), None)
        if icon is not None:
            icon_path = icon.relative_to(ROOT).as_posix()
            published.update({
                "icon_url": f"https://raw.githubusercontent.com/Biosphir/Notcher-apps/{quote(tag, safe='')}/{icon_path}",
                "icon_sha256": hashlib.sha256(icon.read_bytes()).hexdigest(),
            })
        catalog.append(published)
    (output / "catalog.json").write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    print(f"Built {len(catalog)} independent app packages in {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()
    build(args.output.resolve(), args.tag)
