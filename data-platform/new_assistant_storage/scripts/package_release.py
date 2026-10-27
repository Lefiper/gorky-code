"""Архив исходников по явному списку; секреты/окружения/данные не включаются."""

import hashlib
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent.parent
ROOT_FILES = {
    "README.md", "Dockerfile", ".dockerignore", ".gitignore", ".gitattributes",
    ".env.example", ".env.docker.example", "compose.yaml", "compose.full.yaml",
    "requirements.txt", "requirements.lock.txt", "requirements.linux.lock.txt",
}
DIRECTORIES = {"app", "sql", "tests", "scripts", "docs", ".github"}


def source_files():
    candidates = [ROOT / name for name in ROOT_FILES]
    for directory in DIRECTORIES:
        candidates.extend((ROOT / directory).rglob("*"))
    for path in sorted(candidates):
        relative = path.relative_to(ROOT)
        if relative.parts[0] not in DIRECTORIES and relative.as_posix() not in ROOT_FILES:
            continue
        if path.is_symlink() or not path.is_file():
            continue
        if "__pycache__" in relative.parts or path.suffix in {".pyc", ".pyo", ".zip"}:
            continue
        if path.name.startswith(".env") and relative.as_posix() not in ROOT_FILES:
            continue
        yield path, relative.as_posix()


def main():
    destination = ROOT / "dist"
    destination.mkdir(exist_ok=True)
    archive = destination / "assistant-storage-mcp.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
        for path, relative in source_files():
            output.write(path, relative)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (destination / "SHA256SUMS.txt").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    with zipfile.ZipFile(archive) as result:
        names = result.namelist()
        if ".env" in names or ".env.docker" in names or any(".venv/" in name or name.startswith(".git/") for name in names):
            raise RuntimeError("Обнаружен запрещённый файл")
    print(f"Prepared {archive.name}: {len(names)} source files; secrets and local environments excluded.")


if __name__ == "__main__":
    main()
