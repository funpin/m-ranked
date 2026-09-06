from pathlib import Path
from types import SimpleNamespace

from migration.release_manifest import release_identity


def test_runtime_provenance_covers_entrypoints_scripts_assets_and_ignores_evidence(tmp_path: Path, monkeypatch):
    files = {
        "operations/bin/pg-to-legacy-sync": "#!/bin/sh\nexec python3 -m operations.reverse_sync\n",
        "frontend/scripts/visual-parity.mts": "export const fixture = 1;\n",
        "frontend/scripts/browser-server.mjs": "export const port = 1;\n",
        "frontend/public/logo.png": "asset bytes",
        "backend/src/main/resources/application.properties": "server.port=8080\n",
        "backend/admin-evidence/report.json": '{"generatedAt":"first"}',
        "frontend/evidence/report.json": '{"generatedAt":"first"}',
        "frontend/.next-review/build.json": '{"build":"first"}',
    }
    for name, content in files.items():
        path=tmp_path/name
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(content)
    def git(args, **kwargs):
        return SimpleNamespace(stdout=("\0".join(files)+"\0").encode() if args[1]=="ls-files" else "a"*40+"\n")
    monkeypatch.setattr("migration.release_manifest.subprocess.run",git)
    first=release_identity(tmp_path)
    assert {row["path"] for row in first["files"]}==set(list(files)[:5])
    for name in list(files)[5:]:
        (tmp_path/name).write_text("new generated evidence")
    assert release_identity(tmp_path)==first
    for name in list(files)[:5]:
        path=tmp_path/name
        original=path.read_text()
        path.write_text(original+"changed")
        assert release_identity(tmp_path)["sourceManifestSha256"]!=first["sourceManifestSha256"], name
        path.write_text(original)
