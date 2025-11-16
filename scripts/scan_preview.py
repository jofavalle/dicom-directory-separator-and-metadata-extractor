#!/usr/bin/env python3
import os
import sys
import json
import random
from typing import List, Dict, Any, Tuple

import pydicom


def is_file(path: str) -> bool:
    try:
        return os.path.isfile(path)
    except Exception:
        return False


def collect_from_dicomdir(dicomdir_path: str, limit: int = 2000) -> List[str]:
    base_dir = os.path.dirname(os.path.abspath(dicomdir_path))
    ddir = pydicom.dcmread(dicomdir_path, force=True, stop_before_pixels=True)
    files: List[str] = []
    # Iterate all records and collect ReferencedFileID when present
    seq = getattr(ddir, "DirectoryRecordSequence", None)
    if not seq:
        return files
    for rec in seq:
        if "ReferencedFileID" in rec:
            ref = rec.ReferencedFileID
            # Some DICOMDIRs store as MultiValue parts (MultiValue in pydicom >=2.4)
            if hasattr(ref, "__iter__") and not isinstance(ref, (str, bytes)):
                rel = os.path.join(*[str(x) for x in list(ref)])
            else:
                rel = str(ref)
            abs_path = os.path.abspath(os.path.join(base_dir, rel))
            if is_file(abs_path):
                files.append(abs_path)
                if len(files) >= limit:
                    break
    return files


def walk_dicom_folder(root: str, folder: str = "dicom", max_files: int = 4000) -> List[str]:
    start = os.path.join(root, folder)
    results: List[str] = []
    for dirpath, dirnames, filenames in os.walk(start):
        # Pick files regardless of extension; DICOMs on media often lack extension
        for name in filenames:
            path = os.path.join(dirpath, name)
            results.append(path)
            if len(results) >= max_files:
                return results
    return results


KEYS_OF_INTEREST = [
    "PatientID",
    "PatientName",
    "PatientBirthDate",
    "StudyInstanceUID",
    "StudyDate",
    "StudyID",
    "AccessionNumber",
    "SeriesInstanceUID",
    "SeriesNumber",
    "SeriesDescription",
    "ProtocolName",
    "Modality",
    "Manufacturer",
    "ImageType",
    "SOPInstanceUID",
    "InstanceNumber",
]


def safe_get(ds: pydicom.Dataset, key: str) -> Any:
    try:
        if key in ds:
            val = ds.data_element(key).value
            # For PersonName and other VRs, stringify safely
            return str(val)
    except Exception:
        pass
    return None


def summarize(files: List[str], sample_size: int = 50) -> Dict[str, Any]:
    random.seed(42)
    sample = files[:sample_size] if len(files) <= sample_size else random.sample(files, sample_size)
    instances: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    for path in sample:
        try:
            ds = pydicom.dcmread(path, stop_before_pixels=True, force=True)
            row = {k: safe_get(ds, k) for k in KEYS_OF_INTEREST}
            row["_path"] = path
            instances.append(row)
        except Exception as e:
            errors.append({"path": path, "error": str(e)})

    # Aggregations
    patients = {}
    studies = {}
    series = {}
    protocols = {}
    for r in instances:
        patients[r.get("PatientID") or "<NA>"] = True
        studies[r.get("StudyInstanceUID") or f"<NA>-{r.get('PatientID')}"] = True
        series[r.get("SeriesInstanceUID") or f"<NA>-{r.get('StudyInstanceUID')}"] = True
        proto = (r.get("ProtocolName") or r.get("SeriesDescription") or "<NA>").strip()
        protocols[proto] = protocols.get(proto, 0) + 1

    top_protocols = sorted(protocols.items(), key=lambda x: (-x[1], x[0]))[:10]

    return {
        "total_files_found": len(files),
        "sampled": len(instances),
        "read_errors": len(errors),
        "unique_patients_in_sample": len(patients),
        "unique_studies_in_sample": len(studies),
        "unique_series_in_sample": len(series),
        "top_protocols_in_sample": top_protocols,
        "examples": instances[:5],
        "errors_sample": errors[:5],
    }


def main():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    # Accept optional args: dicomdir path and dicom folder
    dicomdir_candidates = [
        os.path.join(root, "dicomdir"),
        os.path.join(root, "DICOMDIR"),
    ]
    use_dicomdir_path = None
    for c in dicomdir_candidates:
        if os.path.exists(c):
            use_dicomdir_path = c
            break

    files: List[str] = []
    if use_dicomdir_path:
        try:
            files = collect_from_dicomdir(use_dicomdir_path)
        except Exception as e:
            print(json.dumps({"warning": f"Failed to parse DICOMDIR: {e}"}, ensure_ascii=False))

    if not files:
        files = walk_dicom_folder(root, folder="dicom", max_files=4000)

    summary = summarize(files, sample_size=80)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
