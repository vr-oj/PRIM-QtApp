# prim_app/utils/path_helpers.py

import os
from datetime import date
from pathlib import Path

from utils.config import PRIM_ROOT


def get_next_fill_folder() -> str:
    """
    Create (if needed) a folder at:
       PRIM_ROOT/YYYY-MM-DD/FillN
    where YYYY-MM-DD = today’s date,
    and N = smallest positive integer so that “FillN” does not yet exist.
    Returns the full path to the newly created “FillN” folder.

    Example return: "/home/alice/Documents/PRIMAcquisition/2025-06-03/Fill1"
    """
    # 1) Today’s date folder: PRIM_ROOT/YYYY-MM-DD
    today = date.today().isoformat()  # e.g. "2025-06-03"
    date_folder = os.path.join(PRIM_ROOT, today)
    Path(date_folder).mkdir(parents=True, exist_ok=True)

    # 2) Look for existing “Fill” subfolders (Fill1, Fill2, …)
    existing = []
    for entry in os.listdir(date_folder):
        if entry.startswith("Fill"):
            suffix = entry[4:]
            if suffix.isdigit():
                existing.append(int(suffix))

    # 3) Pick the next unused integer
    n = 1
    while n in existing:
        n += 1

    # 4) Create the new FillN folder
    new_fill_name = f"Fill{n}"
    new_fill_path = os.path.join(date_folder, new_fill_name)
    Path(new_fill_path).mkdir(parents=True, exist_ok=True)

    return new_fill_path
