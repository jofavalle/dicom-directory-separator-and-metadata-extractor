from __future__ import annotations
import os
from typing import Dict, Any, Tuple
import pandas as pd


def summarize_hierarchy(df: pd.DataFrame) -> pd.DataFrame:
    keys = [k for k in ["PatientID", "StudyInstanceUID", "SeriesInstanceUID", "ProtocolName", "SeriesDescription"] if k in df.columns]
    if not keys:
        return pd.DataFrame()
    grp = df.groupby(keys, dropna=False)
    out = grp.agg(
        n_instances=("SOPInstanceUID" if "SOPInstanceUID" in df.columns else df.columns[0], "count")
    ).reset_index()
    return out


def detect_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    if "SOPInstanceUID" not in df.columns:
        return pd.DataFrame()
    dup_mask = df["SOPInstanceUID"].duplicated(keep=False)
    return df.loc[dup_mask].sort_values(["SOPInstanceUID", "SeriesInstanceUID", "InstanceNumber" if "InstanceNumber" in df.columns else "_path"])  # type: ignore


def detect_instance_gaps(df: pd.DataFrame) -> pd.DataFrame:
    if "InstanceNumber" not in df.columns or "SeriesInstanceUID" not in df.columns:
        return pd.DataFrame()
    # Work on numeric InstanceNumber
    tmp = df.copy()
    tmp["InstanceNumber_num"] = pd.to_numeric(tmp["InstanceNumber"], errors="coerce")
    recs = []
    for sid, g in tmp.groupby("SeriesInstanceUID", dropna=False):
        nums = g["InstanceNumber_num"].dropna().astype(int).sort_values().tolist()
        if not nums:
            continue
        expected = set(range(nums[0], nums[-1] + 1))
        actual = set(nums)
        missing = sorted(expected - actual)
        recs.append({
            "SeriesInstanceUID": sid,
            "min": nums[0],
            "max": nums[-1],
            "n_expected": len(expected),
            "n_actual": len(actual),
            "n_missing": len(missing),
            "missing_list": ",".join(map(str, missing[:50])) + ("…" if len(missing) > 50 else ""),
        })
    return pd.DataFrame(recs)


def missing_critical_tags(df: pd.DataFrame) -> pd.DataFrame:
    crit = ["PatientID", "StudyInstanceUID", "SeriesInstanceUID", "SOPInstanceUID"]
    present = [c for c in crit if c in df.columns]
    if not present:
        return pd.DataFrame()
    mask = False
    for c in present:
        mask = mask | df[c].isna() | (df[c].astype(str) == "") if isinstance(mask, pd.Series) else (df[c].isna() | (df[c].astype(str) == ""))
    return df.loc[mask, present + (["_path"] if "_path" in df.columns else [])]


def run_qa(df_inst: pd.DataFrame, outdir: str) -> Dict[str, Any]:
    qa_dir = os.path.join(outdir, "qa")
    os.makedirs(qa_dir, exist_ok=True)

    hierarchy = summarize_hierarchy(df_inst)
    dups = detect_duplicates(df_inst)
    gaps = detect_instance_gaps(df_inst)
    missing = missing_critical_tags(df_inst)

    paths: Dict[str, str] = {}
    if not hierarchy.empty:
        p = os.path.join(qa_dir, "qa_hierarchy_counts.csv")
        hierarchy.to_csv(p, index=False)
        paths["hierarchy_counts"] = p
    if not dups.empty:
        p = os.path.join(qa_dir, "qa_duplicates_sop.csv")
        dups.to_csv(p, index=False)
        paths["duplicates_sop"] = p
    if not gaps.empty:
        p = os.path.join(qa_dir, "qa_instance_gaps.csv")
        gaps.to_csv(p, index=False)
        paths["instance_gaps"] = p
    if not missing.empty:
        p = os.path.join(qa_dir, "qa_missing_critical_tags.csv")
        missing.to_csv(p, index=False)
        paths["missing_critical_tags"] = p

    return {
        "qa_outputs": paths,
        "summary": {
            "series_with_gaps": int((gaps["n_missing"] > 0).sum()) if not gaps.empty else 0,
            "duplicate_sops": int(dups.shape[0]) if not dups.empty else 0,
            "rows_missing_critical": int(missing.shape[0]) if not missing.empty else 0,
        },
    }
