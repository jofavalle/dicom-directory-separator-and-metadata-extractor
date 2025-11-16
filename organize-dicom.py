#!/usr/bin/env python3
from __future__ import annotations
import argparse
import os
import shutil
from typing import List

import pandas as pd

from ctqtools.indexer import iter_files_from_dicomdir, iter_files_from_folder, build_index
from ctqtools.config import load_config, normalize_protocol
from ctqtools.utils import ensure_dir, sanitize


def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="organize-dicom.py",
        description="Organiza DICOM por prueba (serie) copiando y renombrando para ImageJ. Directorio incluye paciente y protocolo.",
    )
    p.add_argument("--input", default=".", help="Raíz que contiene DICOMDIR o carpeta dicom/")
    p.add_argument("--dicom-folder", default="dicom", help="Subcarpeta con DICOM si no hay DICOMDIR")
    p.add_argument("--output", default="organized", help="Carpeta de salida (carpetas de pruebas y CSVs)")
    p.add_argument("--config", default=None, help="Ruta a config.yaml para normalizar nombres de protocolo")
    p.add_argument("--dry-run", action="store_true", help="No copiar, solo mostrar resumen")
    p.add_argument("--export-metadata", dest="export_metadata", action="store_true", help="Exportar CSVs de metadatos")
    p.add_argument("--no-export-metadata", dest="export_metadata", action="store_false", help="No exportar CSVs de metadatos")
    p.add_argument("--organize", dest="organize", action="store_true", help="Organizar/copiar por prueba con renombrado secuencial")
    #!/usr/bin/env python3
    from ctqtools.organize_dicom import main

    if __name__ == "__main__":
        raise SystemExit(main())
    # Organización avanzada
