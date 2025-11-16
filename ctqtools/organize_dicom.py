from __future__ import annotations
import argparse
import os
import shutil
from typing import List

import pandas as pd

from .indexer import iter_files_from_dicomdir, iter_files_from_folder, build_index
from .config import load_config, normalize_protocol
from .utils import ensure_dir, sanitize


def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="organize-dicom",
        description="Organiza DICOM por prueba (serie), copia/renombra para ImageJ, exporta metadatos y QA.",
    )
    p.add_argument("--input", default=".", help="Raíz que contiene DICOMDIR o carpeta dicom/")
    p.add_argument("--dicom-folder", default="dicom", help="Subcarpeta con DICOM si no hay DICOMDIR")
    p.add_argument("--output", default="organized", help="Carpeta de salida (carpetas de pruebas y CSVs)")
    p.add_argument("--config", default=None, help="Ruta a config.yaml para normalizar nombres de protocolo")
    p.add_argument("--dry-run", action="store_true", help="No copiar, solo mostrar resumen")
    p.add_argument("--export-metadata", dest="export_metadata", action="store_true", help="Exportar CSVs de metadatos")
    p.add_argument("--no-export-metadata", dest="export_metadata", action="store_false", help="No exportar CSVs de metadatos")
    p.add_argument("--organize", dest="organize", action="store_true", help="Organizar/copiar por prueba con renombrado secuencial")
    p.add_argument("--no-organize", dest="organize", action="store_false", help="No organizar/copiar archivos")
    p.add_argument("--qa", dest="qa", action="store_true", help="Generar reportes de QA")
    p.add_argument("--no-qa", dest="qa", action="store_false", help="No generar reportes de QA")
    p.add_argument("--all-tags", action="store_true", help="Exportar todos los tags (CSV más grande)")
    p.add_argument("--workers", type=int, default=8, help="Hilos para lectura de metadatos")
    # Organización avanzada
    p.add_argument("--link-mode", choices=["copy", "hardlink", "symlink"], default="copy", help="Modo de materialización de archivos al organizar")
    p.add_argument("--on-collision", choices=["skip", "overwrite", "rename"], default="skip", help="Qué hacer si el destino ya existe")
    p.add_argument("--pad-width", type=int, default=0, help="Padding fijo para nombres secuenciales (0 = auto)")
    p.add_argument("--copy-workers", type=int, default=4, help="Concurrencia para copiado/enlace al organizar")
    # Filtros
    p.add_argument("--modality", action="append", help="Filtrar por Modality (repetible, p.ej. --modality CT)")
    p.add_argument("--date-range", default=None, help="Filtrar por StudyDate YYYYMMDD:YYYYMMDD (inclusive)")
    p.add_argument("--patient-id", dest="patient_ids", action="append", help="Filtrar por PatientID (repetible)")
    p.add_argument("--protocol-include", default=None, help="Regex para incluir ProtocolNorm")
    p.add_argument("--protocol-exclude", default=None, help="Regex para excluir ProtocolNorm")
    p.set_defaults(export_metadata=True, organize=True, qa=True)
    return p.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    ns = parse_args(argv)
    root = os.path.abspath(ns.input)
    outdir = os.path.abspath(os.path.join(root, ns.output))
    ensure_dir(outdir)

    # Descubrir archivos
    dicomdir_candidates = [os.path.join(root, "dicomdir"), os.path.join(root, "DICOMDIR")]
    inputs = None
    for c in dicomdir_candidates:
        if os.path.exists(c):
            inputs = list(iter_files_from_dicomdir(c))
            break
    if not inputs:
        inputs = list(iter_files_from_folder(os.path.join(root, ns.dicom_folder)))

    # Indexar metadatos
    rows = build_index(inputs, max_workers=ns.workers, all_tags=ns.all_tags)
    df = pd.DataFrame(rows)
    if df.empty:
        print({
            "total_files_seen": len(inputs),
            "indexed_instances": 0,
            "message": "No se pudieron leer metadatos."
        })
        return 0

    # Derivar protocolo normalizado
    cfg = load_config(ns.config)
    proto_eff = (df.get("ProtocolName").fillna("") if "ProtocolName" in df.columns else pd.Series([""] * len(df)))
    if "SeriesDescription" in df.columns:
        mask_empty = (proto_eff.eq("")) | proto_eff.isna()
        proto_eff = proto_eff.where(~mask_empty, df["SeriesDescription"].fillna(""))
    proto_eff = proto_eff.replace("", "NA")
    df["ProtocolEffective"] = proto_eff
    df["ProtocolNorm"] = df["ProtocolEffective"].map(lambda x: normalize_protocol(x, cfg))

    # Filtros
    def apply_filters(df_in: pd.DataFrame) -> pd.DataFrame:
        df_out = df_in
        if ns.modality and "Modality" in df_out.columns:
            df_out = df_out[df_out["Modality"].isin(ns.modality)]
        if ns.date_range and "StudyDate" in df_out.columns:
            try:
                start, end = ns.date_range.split(":", 1)
                start = start.strip() or "00000101"
                end = end.strip() or "99991231"
                df_out = df_out[(df_out["StudyDate"] >= start) & (df_out["StudyDate"] <= end)]
            except Exception:
                pass
        if ns.patient_ids and "PatientID" in df_out.columns:
            df_out = df_out[df_out["PatientID"].isin(ns.patient_ids)]
        import re
        if ns.protocol_include and "ProtocolNorm" in df_out.columns:
            df_out = df_out[df_out["ProtocolNorm"].astype(str).str.contains(ns.protocol_include, case=False, na=False, regex=True)]
        if ns.protocol_exclude and "ProtocolNorm" in df_out.columns:
            df_out = df_out[~df_out["ProtocolNorm"].astype(str).str.contains(ns.protocol_exclude, case=False, na=False, regex=True)]
        return df_out

    df = apply_filters(df)

    # Garantizar columnas base
    for col in ["PatientName", "PatientID", "SeriesInstanceUID"]:
        if col not in df.columns:
            df[col] = "NA"

    created = 0
    copied = 0
    series_cols = [
        "PatientName",
        "PatientID",
        "ProtocolNorm",
        "StudyInstanceUID",
        "SeriesInstanceUID",
        "SeriesNumber" if "SeriesNumber" in df.columns else "SeriesInstanceUID",
    ]

    if ns.organize:
        for key, g in df.groupby(series_cols, dropna=False, sort=False):
            patient_name, patient_id, proto_norm, study_uid, series_uid, series_number = key
            s_patient = sanitize(str(patient_name))
            s_proto = sanitize(str(proto_norm))
            s_seriesnum = sanitize(str(series_number))
            s_seriesuid = sanitize(str(series_uid))

            test_dirname = f"Prueba_{s_patient}__{s_proto}__Series_{s_seriesnum}_{s_seriesuid}"
            target_dir = os.path.join(outdir, test_dirname)
            ensure_dir(target_dir)
            created += 1

            # Deduplicación por SOPInstanceUID
            if "SOPInstanceUID" in g.columns:
                g = g.drop_duplicates(subset=["SOPInstanceUID"], keep="first")

            # Orden
            if "InstanceNumber" in g.columns:
                g = g.copy()
                g["InstanceNumber_num"] = pd.to_numeric(g["InstanceNumber"], errors="coerce")
                g = g.sort_values(["InstanceNumber_num", "_path"], na_position="first")
            else:
                if "ImagePositionPatient" in g.columns:
                    def zpos(val: str) -> float:
                        try:
                            s = str(val)
                            if s.startswith("["):
                                import ast
                                lst = ast.literal_eval(s)
                                return float(lst[2])
                            if "\\" in s:
                                return float(s.split("\\")[2])
                            parts = s.split(",")
                            return float(parts[2]) if len(parts) > 2 else float("nan")
                        except Exception:
                            return float("nan")
                    g = g.copy()
                    g["_zpos"] = g["ImagePositionPatient"].map(zpos)
                    if g["_zpos"].notna().any():
                        g = g.sort_values(["_zpos", "_path"], na_position="first")
                    elif "AcquisitionTime" in g.columns:
                        g = g.sort_values(["AcquisitionTime", "_path"])  # simple fallback temporal
                    else:
                        g = g.sort_values(["_path"])  # fallback
                elif "AcquisitionTime" in g.columns:
                    g = g.sort_values(["AcquisitionTime", "_path"])  # fallback temporal
                else:
                    g = g.sort_values(["_path"])  # fallback

            total = len(g)
            pad = ns.pad_width if ns.pad_width and ns.pad_width > 0 else max(4, len(str(total)))

            from concurrent.futures import ThreadPoolExecutor

            def materialize(src_path: str, dst_path: str) -> str | None:
                # Colisiones
                if os.path.exists(dst_path):
                    if ns.on_collision == "skip":
                        return "skipped"
                    elif ns.on_collision == "overwrite":
                        try:
                            os.remove(dst_path)
                        except FileNotFoundError:
                            pass
                    elif ns.on_collision == "rename":
                        base, ext = os.path.splitext(dst_path)
                        i = 1
                        new_dst = f"{base}__{i}{ext}"
                        while os.path.exists(new_dst):
                            i += 1
                            new_dst = f"{base}__{i}{ext}"
                        dst_path = new_dst
                try:
                    if ns.link_mode == "copy":
                        shutil.copy2(src_path, dst_path)
                    elif ns.link_mode == "hardlink":
                        os.link(src_path, dst_path)
                    else:
                        os.symlink(src_path, dst_path)
                    return dst_path
                except Exception:
                    return None

            manifest_rows = []
            with ThreadPoolExecutor(max_workers=max(1, ns.copy_workers)) as ex:
                futures = []
                for idx, (_, row) in enumerate(g.iterrows(), start=1):
                    src = row.get("_path")
                    if not src or not os.path.exists(str(src)):
                        continue
                    src = str(src)
                    base = os.path.basename(src)
                    _name, ext = os.path.splitext(base)
                    new_name = f"{idx:0{pad}d}{ext}"
                    dst = os.path.join(target_dir, new_name)
                    if ns.dry_run:
                        copied += 1
                        manifest_rows.append({"new_name": new_name, "original_name": base, "src_path": src})
                        continue
                    futures.append((base, new_name, src, ex.submit(materialize, src, dst)))

                for base, new_name, src, fut in futures:
                    res = fut.result()
                    if res is None:
                        continue
                    copied += 1
                    manifest_rows.append({"new_name": os.path.basename(res), "original_name": base, "src_path": src})

            if not ns.dry_run and manifest_rows:
                man_csv = os.path.join(target_dir, "manifest.csv")
                pd.DataFrame(manifest_rows).to_csv(man_csv, index=False)

    # Exportar metadatos y QA
    outputs = {}
    if ns.export_metadata:
        inst_csv = os.path.join(outdir, "global_index_instances.csv")
        if not ns.dry_run:
            df.to_csv(inst_csv, index=False)
        outputs["instances_csv"] = inst_csv

        s_cols = ["PatientID", "StudyInstanceUID", "SeriesInstanceUID", "SeriesNumber" if "SeriesNumber" in df.columns else "SeriesInstanceUID", "ProtocolNorm", "Modality" if "Modality" in df.columns else None]
        s_cols = [c for c in s_cols if c and c in df.columns]  # type: ignore
        grp = df.groupby(s_cols, dropna=False, sort=False)
        base_col = "SOPInstanceUID" if "SOPInstanceUID" in df.columns else (s_cols[0] if s_cols else df.columns[0])
        series_df = grp.agg(
            n_instances=(base_col, "count"),
            instance_min=("InstanceNumber" if "InstanceNumber" in df.columns else base_col, "min"),
            instance_max=("InstanceNumber" if "InstanceNumber" in df.columns else base_col, "max"),
        ).reset_index()
        series_csv = os.path.join(outdir, "global_index_series.csv")
        if not ns.dry_run:
            series_df.to_csv(series_csv, index=False)
        outputs["series_csv"] = series_csv

        csv_dir_pat = os.path.join(outdir, "csv", "patients")
        csv_dir_pp = os.path.join(outdir, "csv", "patient_protocols")
        if not ns.dry_run:
            ensure_dir(csv_dir_pat)
            ensure_dir(csv_dir_pp)

        if "PatientID" in df.columns:
            for pid, g in df.groupby("PatientID", dropna=False, sort=False):
                spid = sanitize(str(pid))
                if not ns.dry_run:
                    g.to_csv(os.path.join(csv_dir_pat, f"patient_{spid}_instances.csv"), index=False)
                if "PatientID" in series_df.columns:
                    ssub = series_df[series_df["PatientID"] == pid]
                    if not ns.dry_run:
                        ssub.to_csv(os.path.join(csv_dir_pat, f"patient_{spid}_series.csv"), index=False)

        if "PatientID" in df.columns and "ProtocolNorm" in df.columns:
            for (pid, proto), g in df.groupby(["PatientID", "ProtocolNorm"], dropna=False, sort=False):
                spid = sanitize(str(pid))
                sproto = sanitize(str(proto))
                if not ns.dry_run:
                    g.to_csv(os.path.join(csv_dir_pp, f"patient_{spid}__protocol_{sproto}_instances.csv"), index=False)

    qa_info = {}
    if ns.qa and ns.export_metadata and not ns.dry_run:
        from .qa import run_qa
        qa_info = run_qa(df, outdir)

    # Resumen CT por Paciente/Protocolo (parámetros: kernel, kVp, ms, mA, mAs, pitch)
    try:
        if ns.export_metadata and not ns.dry_run and "PatientID" in df.columns and "ProtocolNorm" in df.columns:
            params_cols = {
                "ConvolutionKernel": "kernel",
                "KVP": "kvp",
                "ExposureTime": "exposure_time",
                "ExposureTimeInms": "exposure_time_ms",
                "XRayTubeCurrent": "xray_tube_current_mA",
                "Exposure": "exposure_mAs",
                "SpiralPitchFactor": "pitch_spiral",
                "PitchFactor": "pitch_factor",
            }

            work = df.copy()
            # Normalizar tiempo de exposición en ms (prioriza ExposureTimeInms)
            import pandas as _pd
            def _to_float(x):
                try:
                    return float(str(x))
                except Exception:
                    return _pd.NA
            if "ExposureTimeInms" in work.columns:
                work["_ExposureTime_ms"] = work["ExposureTimeInms"].map(_to_float)
            else:
                work["_ExposureTime_ms"] = _pd.NA
            if "ExposureTime" in work.columns:
                et_as_ms = work["ExposureTime"].map(_to_float)
                work["_ExposureTime_ms"] = work["_ExposureTime_ms"].fillna(et_as_ms)

            # Pitch efectivo por fila (SpiralPitchFactor > PitchFactor)
            pitch_cols = []
            if "SpiralPitchFactor" in work.columns:
                pitch_cols.append("SpiralPitchFactor")
            if "PitchFactor" in work.columns:
                pitch_cols.append("PitchFactor")
            if pitch_cols:
                work["_Pitch"] = work[pitch_cols].bfill(axis=1).iloc[:, 0]
            else:
                work["_Pitch"] = _pd.NA

            def uniq_join(series):
                vals = [str(v) for v in series.dropna().astype(str).unique() if str(v).strip() not in ("", "None", "nan")]
                return " | ".join(sorted(vals)) if vals else ""

            grp_cols = ["PatientID", "ProtocolNorm"]
            if "PatientName" in work.columns:
                # mantener PatientName de apoyo (único por paciente si viene limpio)
                grp_cols_display = ["PatientID", "PatientName", "ProtocolNorm"]
            else:
                grp_cols_display = grp_cols

            g = work.groupby(grp_cols, dropna=False, sort=False)
            summary = g.agg(
                n_series=("SeriesInstanceUID", "nunique") if "SeriesInstanceUID" in work.columns else ("SOPInstanceUID", "nunique"),
                n_instances=("SOPInstanceUID", "count") if "SOPInstanceUID" in work.columns else (work.columns[0], "count"),
                kernel=("ConvolutionKernel", uniq_join) if "ConvolutionKernel" in work.columns else (work.columns[0], lambda s: ""),
                kvp=("KVP", uniq_join) if "KVP" in work.columns else (work.columns[0], lambda s: ""),
                exposure_time_ms=("_ExposureTime_ms", uniq_join),
                xray_tube_current_mA=("XRayTubeCurrent", uniq_join) if "XRayTubeCurrent" in work.columns else (work.columns[0], lambda s: ""),
                exposure_mAs=("Exposure", uniq_join) if "Exposure" in work.columns else (work.columns[0], lambda s: ""),
                pitch=("_Pitch", uniq_join),
            ).reset_index()

            # Reordenar columnas para legibilidad
            desired = []
            for c in ["PatientID", "PatientName", "ProtocolNorm", "n_series", "n_instances", "kernel", "kvp", "exposure_time_ms", "xray_tube_current_mA", "exposure_mAs", "pitch"]:
                if c in summary.columns:
                    desired.append(c)
            summary = summary[desired]

            out_dir_pp = os.path.join(outdir, "csv", "patient_protocols")
            ensure_dir(out_dir_pp)
            out_summary = os.path.join(out_dir_pp, "summary_ct_params_by_patient_protocol.csv")
            summary.to_csv(out_summary, index=False)
            outputs["ct_params_summary_csv"] = out_summary
    except Exception:
        pass

    print({
        "total_files_seen": len(inputs),
        "indexed_instances": len(df),
        "tests_created": created if ns.organize else 0,
        "files_copied": copied if ns.organize else 0,
        "export_metadata": ns.export_metadata,
        "qa": qa_info,
        "output_dir": outdir,
        "note": "Extensiones preservadas; nombres renombrados secuencialmente para ImageJ."
    })
    return 0
