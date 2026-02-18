# scripts/flash_srmodels.py
Import("env")
import os, csv, subprocess, sys

def find_partition_offset(csv_path, name_candidates=("model", "srmodels", "esp_sr")):
    with open(csv_path, newline="") as f:
        rows = csv.reader(f)
        for row in rows:
            if not row or row[0].strip().startswith("#"):
                continue
            # CSV: Name, Type, SubType, Offset, Size, Flags
            name = row[0].strip()
            if name in name_candidates:
                off = row[3].strip()
                if not off:
                    raise RuntimeError("Partition offset is empty; please set explicit Offset in CSV.")
                return int(off, 0)
    raise RuntimeError(f"Model partition not found in {csv_path}. Expected one of {name_candidates}.")

def after_upload(source, target, env):
    proj = env["PROJECT_DIR"]
    csv_path = os.path.join(proj, env.BoardConfig().get("build.partitions", "partitions.csv"))
    # arduino-esp32のsrmodels.bin（PlatformIOのframeworkパッケージ内にある前提）
    framework_dir = env.PioPlatform().get_package_dir("framework-arduinoespressif32")
    chip = env.BoardConfig().get("build.mcu", "esp32s3")  # CoreS3ならesp32s3想定
    srmodels = os.path.join("misc" , "ESP_SR", "srmodels_only_histackchan.bin")

    if not os.path.exists(srmodels):
        raise RuntimeError(f"srmodels.bin not found: {srmodels}")

    offset = find_partition_offset(csv_path)

    port = env.subst("$UPLOAD_PORT")
    speed = env.subst("$UPLOAD_SPEED")
    esptool = env.subst("$PYTHONEXE") + " " + env.PioPlatform().get_package_dir("tool-esptoolpy") + "/esptool.py"

    cmd = f'{esptool} --chip {chip} --port "{port}" --baud {speed} write_flash {hex(offset)} "{srmodels}"'
    print("Flashing srmodels:", cmd)
    ret = subprocess.call(cmd, shell=True)
    if ret != 0:
        raise RuntimeError(f"esptool write_flash failed with code {ret}")

env.AddPostAction("upload", after_upload)
