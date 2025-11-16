import argparse
import os
import sys
from typing import List

import pandas as pd

from .indexer import (
    iter_files_from_dicomdir,
    iter_files_from_folder,
    build_index,
)
from .utils import ensure_dir, sanitize
from .config import load_config, normalize_protocol
from .qa import run_qa


def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="ctq",
        description="Organiza DICOM por paciente/protocolo y exporta metadatos",
    )
    p.add_argument("--input", default=".", help="Raíz del estudio (contiene DICOMDIR o carpeta dicom/")
    p.add_argument("--dicom-folder", default="dicom", help="Subcarpeta con DICOM si no hay DICOMDIR")
    p.add_argument("--output", default="output", help="Carpeta de salida para CSVs y organización")
    p.add_argument("--all-tags", action="store_true", help="Exportar todos los tags a nivel instancia")
    p.add_argument("--workers", type=int, default=8, help="Hilos para lectura de metadatos")
    p.add_argument("--organize", action="store_true", help="Crear estructura por Paciente/Protocolo/Estudio/Serie (symlinks)")
    p.add_argument("--dry-run", action="store_true", help="No escribir cambios, solo mostrar resumen")
    p.add_argument("--qa", action="store_true", help="Generar reportes de QA (gaps, duplicados, jerarquía, tags críticos)")
    p.add_argument("--config", default=None, help="Ruta a config.yaml para normalizar nombres de protocolo")
    return p.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    ns = parse_args(sys.argv[1:] if argv is None else argv)
    root = os.path.abspath(ns.input)
    outdir = os.path.abspath(os.path.join(root, ns.output))
    ensure_dir(outdir)

    dicomdir_candidates = [os.path.join(root, "dicomdir"), os.path.join(root, "DICOMDIR")]
    inputs = None
    for c in dicomdir_candidates:
        if os.path.exists(c):
            inputs = list(iter_files_from_dicomdir(c))
            break
    if not inputs:
        inputs = list(iter_files_from_folder(os.path.join(root, ns.dicom_folder)))

    # Build instance-level index
    rows = build_index(inputs, max_workers=ns.workers, all_tags=ns.all_tags)
    df = pd.DataFrame(rows)
    if df.empty:
        print({
            "total_files_seen": len(inputs),
            "indexed_instances": 0,
            "message": "No se pudo leer metadatos de ningún archivo. Verifique permisos o integridad.",
        })
        return 0

    # Write global instances CSV
    inst_csv = os.path.join(outdir, "global_index_instances.csv")
    if not ns.dry_run:
        df.to_csv(inst_csv, index=False)

    # Normalize protocol names if config provided
    cfg = load_config(ns.config)
    proto_eff = (df.get("ProtocolName").fillna("") if "ProtocolName" in df.columns else pd.Series([""] * len(df)))
    if "SeriesDescription" in df.columns:
        mask_empty = (proto_eff.eq("")) | proto_eff.isna()
        proto_eff = proto_eff.where(~mask_empty, df["SeriesDescription"].fillna(""))
    proto_eff = proto_eff.replace("", "NA")
    df["ProtocolEffective"] = proto_eff
    df["ProtocolNorm"] = df["ProtocolEffective"].map(lambda x: normalize_protocol(x, cfg))

    # Series-level aggregation
    series_cols = [
        "PatientID",
        "StudyInstanceUID",
        "SeriesInstanceUID",
        "SeriesNumber",
        "ProtocolNorm",
        "Modality",
    ]
    existing_cols = [c for c in series_cols if c in df.columns]
    grp = df.groupby(existing_cols, dropna=False, sort=False)
    base_col = "SOPInstanceUID" if "SOPInstanceUID" in df.columns else (existing_cols[0] if existing_cols else df.columns[0])
    series_df = grp.agg(
        n_instances=(base_col, "count"),
        instance_min=("InstanceNumber" if "InstanceNumber" in df.columns else base_col, "min"),
        instance_max=("InstanceNumber" if "InstanceNumber" in df.columns else base_col, "max"),
    ).reset_index()

    series_csv = os.path.join(outdir, "global_index_series.csv")
    if not ns.dry_run:
        series_df.to_csv(series_csv, index=False)

    # Exports per-patient and per patient/protocol
    csv_dir_pat = os.path.join(outdir, "csv", "patients")
    csv_dir_pp = os.path.join(outdir, "csv", "patient_protocols")
    if not ns.dry_run:
        ensure_dir(csv_dir_pat)
        ensure_dir(csv_dir_pp)

    # Per patient instances and series
    if "PatientID" in df.columns:
        for pid, g in df.groupby("PatientID", dropna=False, sort=False):
            spid = sanitize(str(pid))
            if not ns.dry_run:
                g.to_csv(os.path.join(csv_dir_pat, f"patient_{spid}_instances.csv"), index=False)
            # series subset for this patient
            if "PatientID" in series_df.columns:
                ssub = series_df[series_df["PatientID"] == pid]
                if not ns.dry_run:
                    ssub.to_csv(os.path.join(csv_dir_pat, f"patient_{spid}_series.csv"), index=False)

    # Per patient/protocol instances
    if "PatientID" in df.columns and "ProtocolEffective" in df.columns:
        for (pid, proto), g in df.groupby(["PatientID", "ProtocolEffective"], dropna=False, sort=False):
            spid = sanitize(str(pid))
            sproto = sanitize(str(proto))
            if not ns.dry_run:
                g.to_csv(os.path.join(csv_dir_pp, f"patient_{spid}__protocol_{sproto}_instances.csv"), index=False)

    # Optional: organize into folders with symlinks
    if ns.organize and not ns.dry_run:
        for _, srow in series_df.iterrows():
            pid = sanitize(str(srow.get("PatientID", "NA")))
            proto = sanitize(str(srow.get("ProtocolNorm") or "NA"))
            study = sanitize(str(srow.get("StudyInstanceUID", "NA")))
            series = sanitize(str(srow.get("SeriesInstanceUID", "NA")))
            target_dir = os.path.join(outdir, f"Patient_{pid}", f"Protocol_{proto}", f"Study_{study}", f"Series_{series}")
            ensure_dir(target_dir)
            # Subset of instances for this series
            mask = (df.get("PatientID") == srow.get("PatientID")) & (df.get("SeriesInstanceUID") == srow.get("SeriesInstanceUID"))
            sub = df[mask]
            for _, irow in sub.iterrows():
                src = str(irow.get("_path"))
                if not src or not os.path.exists(src):
                    continue
                base = os.path.basename(src)
                dst = os.path.join(target_dir, base)  # conserva el nombre y la extensión original
                try:
                    if not os.path.exists(dst):
                        os.symlink(src, dst)
                except FileExistsError:
                    pass
                except OSError:
                    # En algunos FS sin symlinks, copiar como fallback controlado
                    # Atención: no cambia la extensión
                    try:
                        import shutil
                        shutil.copy2(src, dst)
                    except Exception:
                        continue

    # QA reports
    qa_info = {}
    if ns.qa and not ns.dry_run:
        qa_info = run_qa(df, outdir)

    # Print concise summary
    print({
        "total_files_seen": len(inputs),
        "indexed_instances": len(df),
        "unique_series": len(series_df),
        "outputs": {
            "instances_csv": inst_csv,
            "series_csv": series_csv,
            "patients_csv_dir": csv_dir_pat,
            "patient_protocol_csv_dir": csv_dir_pp,
            "organized": bool(ns.organize and not ns.dry_run),
            "output_dir": outdir,
            "qa": qa_info,
        }
    })

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
