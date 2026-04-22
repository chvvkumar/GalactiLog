import re
import os
from pathlib import Path

_NAME_RE = re.compile(r'_\("(.+?)"\)')

PREFIX_MAP = {
    "NGC":  "NGC",
    "IC":   "IC",
    "M":    "M",
    "SH2":  "Sh2-",
    "B":    "Barnard",
    "CR":   "Collinder",
    "MEL":  "Melotte",
    "LDN":  "LDN",
    "LBN":  "LBN",
    "RCW":  "RCW",
    "VDB":  "vdB",
    "CED":  "Ced",
    "GUM":  "Gum",
    "PAL":  "Palomar",
    "ST":   "Stock",
    "ACO":  "ACO",
    "PGC":  "PGC",
    "HCG":  "HCG",
    "ARP":  "Arp",
    "DWB":  "DWB",
    "SNRG": "SNR G",
}

_HYPHENATED = {"Sh2-"}


def _to_simbad_id(prefix: str, obj_id: str) -> str:
    mapped = PREFIX_MAP.get(prefix.upper(), prefix)
    if mapped in _HYPHENATED:
        return f"{mapped}{obj_id}"
    return f"{mapped} {obj_id}"


def parse_names_dat(lines: list[str]) -> dict[str, str]:
    names: dict[str, str] = {}
    for line in lines:
        if not line.strip() or line.strip().startswith("#"):
            continue
        if len(line) < 21:
            continue
        prefix = line[0:5].strip()
        obj_id = line[5:20].strip()
        remainder = line[20:]
        match = _NAME_RE.search(remainder)
        if not match or not prefix or not obj_id:
            continue
        common_name = match.group(1).lower()
        if common_name not in names:
            simbad_id = _to_simbad_id(prefix, obj_id)
            names[common_name] = simbad_id
    return names


_cache: dict[str, str] | None = None


def get_stellarium_names() -> dict[str, str]:
    global _cache
    if _cache is not None:
        return _cache
    dat_path = Path(__file__).resolve().parent.parent.parent / "data" / "catalogs" / "names.dat"
    with open(dat_path, encoding="utf-8") as f:
        _cache = parse_names_dat(f.readlines())
    return _cache
