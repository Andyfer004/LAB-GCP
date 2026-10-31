"""Desde lab/: python configure_simulator.py. Toma la URL real de Terraform."""
import json
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parent
url = subprocess.check_output(["terraform", "-chdir=" + str(root / "infra"),
                               "output", "-raw", "function_url"], text=True).strip()
path = root / "simulator" / "config.local.json"
source = path if path.exists() else path.with_name("config.example.json")
config = json.loads(source.read_text())
config["target_url"] = url
path.write_text(json.dumps(config, indent=2) + "\n")
print(f"target_url configurado: {url}")
