"""Register the official wheel's native libraries and check the active binding.

Run as root during image build, before importing tgw. No SDK login is performed.
"""
from importlib.metadata import distribution
from pathlib import Path
import subprocess
import sys


def main():
    package = Path(distribution("tgw").locate_file("tgw")).resolve()
    common = package / "common_linux_lib64"
    version = f"{sys.version_info.major}{sys.version_info.minor}"
    binding = package / f"linux_py{version}_x64_package" / f"libtgw_python{version}.so"
    if not common.is_dir() or not binding.is_file():
        raise SystemExit(f"官方 tgw wheel 缺少当前 Python 的 Linux 库: {binding}")
    Path("/etc/ld.so.conf.d/tgw.conf").write_text(str(common) + "\n")
    subprocess.run(["ldconfig"], check=True)
    result = subprocess.run(["ldd", str(binding)], capture_output=True, text=True, check=True)
    missing = [line.strip() for line in result.stdout.splitlines() if "not found" in line]
    if missing:
        raise SystemExit("tgw 当前扩展仍缺少动态库:\n" + "\n".join(missing))
    print(f"tgw Python {version} 原生库依赖检查通过: {binding}", flush=True)


if __name__ == "__main__":
    main()
