"""Audita archivos preparados para publicar; no lee almacenes de credenciales."""
import argparse
import base64
import json
from pathlib import Path
import re
import subprocess

PATTERNS = {
    "clave privada": r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    "clave API Google": r"AIza[0-9A-Za-z_-]{30,}",
    "token OAuth": r"ya29\.[0-9A-Za-z_-]{20,}",
    "token GitHub": r"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})",
    "clave AWS": r"(?:AKIA|ASIA)[A-Z0-9]{16}",
    "credencial JSON": r'"(?:private_key|refresh_token|client_secret|access_token)"\s*:\s*"[^"\s]{8,}"',
    "cuenta de servicio": r'"type"\s*:\s*"service_account"',
    "correo personal": r"[A-Z0-9._%+-]+@(?:gmail|hotmail|outlook|yahoo)\.[A-Z]{2,}",
    "identidad GCP": r"[A-Z0-9_.+-]+@[A-Z0-9-]+\.iam\.gserviceaccount\.com",
    "URL real de función": r"https://[A-Za-z0-9-]+\.a\.run\.app",
    "URL de dashboard real": r"https://console\.cloud\.google\.com/monitoring/dashboards/builder/[0-9a-f-]{30,}",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--forbidden-file", type=Path,
                        help="Lista JSON local de identificadores que no deben publicarse")
    parser.add_argument("--ocr", action="store_true", help="Revisar PNG con tesseract")
    args = parser.parse_args()
    forbidden = json.loads(args.forbidden_file.read_text()) if args.forbidden_file else []
    findings, reviewed = [], 0

    def inspect(text, name):
        for label, pattern in PATTERNS.items():
            if re.search(pattern, text, re.I):
                findings.append({"file": name, "reason": label})
        for marker in forbidden:
            if marker and marker.lower() in text.lower():
                findings.append({"file": name, "reason": "identificador privado conocido"})

    for path in sorted(args.root.rglob("*")):
        if not path.is_file() or ".git" in path.relative_to(args.root).parts:
            continue
        rel = str(path.relative_to(args.root))
        reviewed += 1
        if (".terraform" in path.parts or path.name.endswith((".tfstate", ".tfplan", ".pem", ".key", ".p12"))
                or ".tfstate." in path.name or path.name.endswith(".tfvars")
                or path.name in (".env", "application_default_credentials.json")):
            findings.append({"file": rel, "reason": "archivo privado o estado de despliegue"})
        if path.suffix == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(str(path))
            inspect("\n".join(page.extract_text() or "" for page in reader.pages), rel)
            inspect(str(reader.metadata), rel + " metadata")
            for page in reader.pages:
                for ref in page.get("/Annots", []):
                    inspect(str(ref.get_object()), rel + " anotaciones")
        elif path.suffix == ".png":
            from PIL import Image
            with Image.open(path) as im:
                inspect(str(im.info), rel + " metadata")
            if args.ocr:
                result = subprocess.run(["tesseract", str(path), "stdout", "--psm", "11"],
                                        text=True, capture_output=True, check=True)
                inspect(result.stdout, rel + " OCR")
        elif path.suffix not in (".zip", ".jpg", ".jpeg"):
            source = path.read_text()
            # El base64 de una imagen puede contener secuencias parecidas a claves.
            # Revisar el documento y los metadatos decodificados por separado.
            visible_source = re.sub(r"data:image/png;base64,[A-Za-z0-9+/=]+", "[imagen PNG]", source) if path.suffix == ".html" else source
            inspect(visible_source, rel)
            if path.suffix == ".html":
                for encoded in re.findall(r"data:image/png;base64,([A-Za-z0-9+/=]+)", path.read_text()):
                    from PIL import Image
                    from io import BytesIO
                    with Image.open(BytesIO(base64.b64decode(encoded))) as im:
                        inspect(str(im.info), rel + " imagen incrustada")
    print(json.dumps({"reviewed_files": reviewed, "findings": findings,
                      "image_ocr": args.ocr}, indent=2, ensure_ascii=False))
    raise SystemExit(bool(findings))


if __name__ == "__main__":
    main()
