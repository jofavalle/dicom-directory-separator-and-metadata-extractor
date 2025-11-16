import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, Iterable, List

import pydicom


DEFAULT_KEYS = [
    "PatientID",
    "PatientName",
    "PatientBirthDate",
    "StudyInstanceUID",
    "StudyDate",
    "AcquisitionTime",
    "StudyID",
    "AccessionNumber",
    "SeriesInstanceUID",
    "SeriesNumber",
    "SeriesDescription",
    "ProtocolName",
    "Modality",
    "Manufacturer",
    "ImageType",
    "ImagePositionPatient",
    "SOPInstanceUID",
    "InstanceNumber",
    # CT exposure/recon parameters (when available)
    "ConvolutionKernel",
    "KVP",
    "ExposureTime",
    "ExposureTimeInms",
    "XRayTubeCurrent",
    "Exposure",
    "SpiralPitchFactor",
    "PitchFactor",
]


def flatten_dataset(ds: pydicom.Dataset) -> Dict[str, Any]:
    row: Dict[str, Any] = {}
    for elem in ds.iterall():
        try:
            name = elem.keyword or elem.name.replace(" ", "")
            if elem.VR == "SQ":
                # Serialize sequences to compact JSON-like strings
                row[name] = f"SQ[{len(elem.value)}]"
                continue
            val = elem.value
            row[name] = str(val)
        except Exception:
            continue
    return row


def read_metadata(path: str, all_tags: bool = False) -> Dict[str, Any]:
    ds = pydicom.dcmread(path, stop_before_pixels=True, force=True)
    if all_tags:
        row = flatten_dataset(ds)
    else:
        # Avoid using `k in ds` with non-standard keywords (e.g., PitchFactor) to prevent warnings.
        row = {}
        for k in DEFAULT_KEYS:
            try:
                v = getattr(ds, k, None)
            except Exception:
                v = None
            row[k] = str(v) if v is not None else None
    row["_path"] = path
    try:
        row["_size_bytes"] = os.path.getsize(path)
    except Exception:
        row["_size_bytes"] = None
    return row


def iter_files_from_dicomdir(dicomdir_path: str) -> Iterable[str]:
    base_dir = os.path.dirname(os.path.abspath(dicomdir_path))
    ddir = pydicom.dcmread(dicomdir_path, force=True, stop_before_pixels=True)
    seq = getattr(ddir, "DirectoryRecordSequence", [])
    for rec in seq:
        if "ReferencedFileID" in rec:
            ref = rec.ReferencedFileID
            if hasattr(ref, "__iter__") and not isinstance(ref, (str, bytes)):
                rel = os.path.join(*[str(x) for x in list(ref)])
            else:
                rel = str(ref)
            abs_path = os.path.abspath(os.path.join(base_dir, rel))
            if os.path.isfile(abs_path):
                yield abs_path


def iter_files_from_folder(root: str) -> Iterable[str]:
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            yield os.path.join(dirpath, name)


def build_index(
    inputs: Iterable[str],
    max_workers: int = 8,
    all_tags: bool = False,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    futures = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for path in inputs:
            futures.append(ex.submit(read_metadata, path, all_tags))
        for fut in as_completed(futures):
            try:
                rows.append(fut.result())
            except Exception:
                continue
    return rows
