"""Шаги установки: учётные записи, каталоги, секреты, окружение, юниты, PKI.

Каждый шаг идемпотентен. Повторный запуск установщика на уже настроенной
машине ничего не ломает и не перегенерирует секреты: пароль, который уже
выдан роли в базе, менять молча нельзя.
"""
from __future__ import annotations

import os
import pwd
import grp
import secrets
import shutil
import string
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Sequence


ETC = Path("/etc/m-ranked")
CREDENTIALS = ETC / "credentials"
PKI = ETC / "pki"
STATE = Path("/var/lib/m-ranked")
UNITS = Path("/etc/systemd/system")
ALPHABET = string.ascii_letters + string.digits


@dataclass
class Context:
    """Что установщик знает о машине и о выбранном способе установки."""

    profile: str
    release: Path
    answers: dict[str, str] = field(default_factory=dict)
    dry_run: bool = False
    log: list[str] = field(default_factory=list)

    def note(self, message: str) -> None:
        self.log.append(message)
        print(f"  {message}", flush=True)

    def run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        if self.dry_run:
            self.note(f"[сухой прогон] {' '.join(args)}")
            return subprocess.CompletedProcess(args, 0, "", "")
        return subprocess.run(args, capture_output=True, text=True, check=check)


def password(length: int = 48) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def ensure_group(context: Context, name: str) -> None:
    try:
        grp.getgrnam(name)
        return
    except KeyError:
        pass
    context.run("groupadd", "--system", name)
    context.note(f"создана группа {name}")


def ensure_user(context: Context, name: str, group: str | None = None) -> None:
    group = group or name
    ensure_group(context, group)
    try:
        pwd.getpwnam(name)
        return
    except KeyError:
        pass
    context.run(
        "useradd", "--system", "--gid", group,
        "--home-dir", f"/home/{name}", "--no-create-home",
        "--shell", "/usr/sbin/nologin", name,
    )
    context.note(f"создана учётная запись {name}")


def ensure_directory(
    context: Context, path: Path, mode: int,
    owner: str | None = None, group: str | None = None,
) -> None:
    if context.dry_run:
        context.note(f"[сухой прогон] каталог {path} {mode:o} {owner or 'root'}")
        return
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(mode)
    if owner:
        shutil.chown(path, user=owner, group=group or owner)
    context.note(f"каталог {path} ({mode:o}, {owner or 'root'})")


def write_secret(context: Context, path: Path, value: str, owner: str = "root") -> None:
    """Записать секрет, не перезаписывая уже существующий.

    Перевыпуск пароля, который уже стоит у роли в базе, оставил бы службу без
    доступа. Существующий файл — источник истины.
    """
    if path.exists():
        context.note(f"секрет {path.name} уже есть, оставлен как есть")
        return
    if context.dry_run:
        context.note(f"[сухой прогон] секрет {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if value.endswith("\n") else value + "\n", encoding="utf-8")
    path.chmod(0o400)
    shutil.chown(path, user=owner, group=owner)
    context.note(f"создан секрет {path.name}")


def render_env(
    context: Context, example: Path, target: Path,
    overrides: Mapping[str, str], mode: int = 0o644,
) -> None:
    """Собрать файл окружения из примера, подставив ответы установщику.

    Пример остаётся единственным местом, где перечислены все переменные с
    объяснениями. Установщик только заменяет значения, а не пишет свой файл:
    иначе примеры и рабочие файлы разъезжаются на первой же правке.
    """
    if target.exists():
        context.note(f"{target.name} уже есть, оставлен как есть")
        return
    lines = example.read_text(encoding="utf-8").splitlines(keepends=True)
    applied: set[str] = set()
    result: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            name = stripped.split("=", 1)[0]
            if name in overrides:
                result.append(f"{name}={overrides[name]}\n")
                applied.add(name)
                continue
        result.append(line)
    for name, value in overrides.items():
        if name not in applied:
            result.append(f"{name}={value}\n")
    if context.dry_run:
        context.note(f"[сухой прогон] {target} ({len(overrides)} значений)")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(result), encoding="utf-8")
    target.chmod(mode)
    context.note(f"записан {target.name}")


def install_units(context: Context, names: Sequence[str]) -> None:
    source = context.release / "operations" / "systemd"
    for name in names:
        origin = source / name
        if not origin.exists():
            context.note(f"ВНИМАНИЕ: юнита {name} нет в релизе")
            continue
        if context.dry_run:
            context.note(f"[сухой прогон] юнит {name}")
            continue
        shutil.copy2(origin, UNITS / name)
        (UNITS / name).chmod(0o644)
    context.note(f"установлено юнитов: {len(names)}")


def install_dropins(context: Context, directory: str, values: Mapping[str, str]) -> None:
    """Положить drop-in'ы профиля, подставив адреса вместо примеров."""
    source = context.release / "operations" / "systemd" / directory
    if not source.is_dir():
        return
    for unit_dir in sorted(source.iterdir()):
        if not unit_dir.is_dir():
            continue
        target = UNITS / unit_dir.name
        for item in sorted(unit_dir.iterdir()):
            name = item.name
            if name.endswith(".example"):
                name = name[: -len(".example")]
            body = item.read_text(encoding="utf-8")
            for placeholder, value in values.items():
                body = body.replace(placeholder, value)
            if context.dry_run:
                context.note(f"[сухой прогон] drop-in {unit_dir.name}/{name}")
                continue
            target.mkdir(parents=True, exist_ok=True)
            (target / name).write_text(body, encoding="utf-8")
            (target / name).chmod(0o644)
            context.note(f"drop-in {unit_dir.name}/{name}")


def daemon_reload(context: Context) -> None:
    context.run("systemctl", "daemon-reload")
    context.note("systemd перечитал юниты")


def verify_units(context: Context, names: Iterable[str]) -> list[str]:
    problems: list[str] = []
    for name in names:
        path = UNITS / name
        if not path.exists():
            continue
        result = context.run("systemd-analyze", "verify", str(path), check=False)
        output = (result.stderr or "").strip()
        if output:
            problems.append(f"{name}: {output.splitlines()[0]}")
    return problems


def enable_units(context: Context, names: Sequence[str], start: bool) -> None:
    for name in names:
        context.run("systemctl", "enable", name, check=False)
    context.note(f"включено в автозагрузку: {len(names)}")
    if start:
        for name in names:
            context.run("systemctl", "start", name, check=False)
        context.note("службы запущены")


# --- PKI переноса -----------------------------------------------------------

def issue_transfer_ca(context: Context) -> None:
    ca_key, ca_crt = PKI / "transfer-ca.key", PKI / "transfer-ca.crt"
    if ca_crt.exists():
        context.note("удостоверяющий центр переноса уже выпущен")
        return
    ensure_directory(context, PKI, 0o700)
    context.run(
        "openssl", "req", "-x509", "-newkey", "ed25519", "-nodes",
        "-days", "3650", "-keyout", str(ca_key), "-out", str(ca_crt),
        "-subj", "/O=m-ranked/CN=m-ranked transfer CA",
        "-addext", "basicConstraints=critical,CA:TRUE,pathlen:0",
        "-addext", "keyUsage=critical,keyCertSign,cRLSign",
    )
    context.note("выпущен удостоверяющий центр переноса (10 лет)")


def _sign(context: Context, name: str, subject: str, extensions: str) -> None:
    key, csr, crt = PKI / f"{name}.key", PKI / f"{name}.csr", PKI / f"{name}.crt"
    if crt.exists():
        context.note(f"сертификат {name} уже выпущен")
        return
    context.run(
        "openssl", "req", "-newkey", "ed25519", "-nodes",
        "-keyout", str(key), "-out", str(csr), "-subj", subject,
    )
    extension_file = PKI / f"{name}.ext"
    if not context.dry_run:
        extension_file.write_text(extensions, encoding="utf-8")
    context.run(
        "openssl", "x509", "-req", "-in", str(csr),
        "-CA", str(PKI / "transfer-ca.crt"), "-CAkey", str(PKI / "transfer-ca.key"),
        "-CAcreateserial", "-days", "365", "-out", str(crt),
        "-extfile", str(extension_file),
    )
    if not context.dry_run:
        csr.unlink(missing_ok=True)
        extension_file.unlink(missing_ok=True)
        key.chmod(0o400)
        crt.chmod(0o400)
    context.note(f"выпущен сертификат {name} (1 год)")


def issue_server_certificate(context: Context, address: str) -> None:
    """Сертификат приёмника. Клиент проверяет имя хоста, поэтому адрес важен."""
    kind = "IP" if address.replace(".", "").isdigit() else "DNS"
    _sign(
        context, "transfer-server", f"/O=m-ranked/CN={address}",
        "basicConstraints=critical,CA:FALSE\n"
        "keyUsage=critical,digitalSignature\n"
        "extendedKeyUsage=serverAuth\n"
        f"subjectAltName={kind}:{address}\n",
    )


def issue_client_certificate(context: Context, producer: str) -> None:
    """Сертификат сборщика. Общее имя обязано совпасть с producer_id."""
    _sign(
        context, producer, f"/O=m-ranked/CN={producer}",
        "basicConstraints=critical,CA:FALSE\n"
        "keyUsage=critical,digitalSignature\n"
        "extendedKeyUsage=clientAuth\n"
        f"subjectAltName=DNS:{producer}\n",
    )


def place_credential(context: Context, source: Path, name: str) -> None:
    if context.dry_run:
        context.note(f"[сухой прогон] credential {name}")
        return
    if not source.exists():
        context.note(f"ВНИМАНИЕ: нет файла {source}")
        return
    target = CREDENTIALS / name
    shutil.copy2(source, target)
    target.chmod(0o400)
    context.note(f"credential {name}")


def write_pgpass(context: Context, name: str, role: str, secret: str,
                 host: str = "127.0.0.1", port: int = 5432,
                 database: str = "mranked") -> None:
    target = CREDENTIALS / name
    if target.exists():
        context.note(f"{name} уже есть, оставлен как есть")
        return
    if context.dry_run:
        context.note(f"[сухой прогон] pgpass {name} для {role}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"{host}:{port}:{database}:{role}:{secret}\n", encoding="utf-8")
    target.chmod(0o400)
    context.note(f"pgpass {name} для роли {role}")
