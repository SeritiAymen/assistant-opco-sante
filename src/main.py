import hashlib
import json
import re
from datetime import datetime
from functools import partial
from pathlib import Path

import pdfplumber

from src.domain.exceptions import DocumentRejectedError

MONTHS = {
    "janvier": "01",
    "février": "02",
    "mars": "03",
    "avril": "04",
    "mai": "05",
    "juin": "06",
    "juillet": "07",
    "août": "08",
    "septembre": "09",
    "octobre": "10",
    "novembre": "11",
    "décembre": "12",
}

DATA_DIR = Path("data")

INGESTION_VERSION = "1.0"


def is_inside(obj, bbox):
    return (
        obj["x0"] >= bbox[0]
        and obj["top"] >= bbox[1]
        and obj["x1"] <= bbox[2]
        and obj["bottom"] <= bbox[3]
    )


def must_conserve_table(obj, bboxes):
    if obj["object_type"] != "char":
        return True
    for bbox in bboxes:
        if is_inside(obj, bbox) and obj["non_stroking_color"] != (1.0,):
            return False

    return True


def must_conserve_text(obj, bboxes):
    for bbox in bboxes:
        if is_inside(obj, bbox):
            return False
    return True


def extract_document(pdf_path, sector):
    full_content = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            tables = page.find_tables(
                table_settings={"horizontal_strategy": "lines_strict"}
            )
            bboxs = [table.rows[0].bbox for table in tables]
            filter_table = partial(must_conserve_table, bboxes=bboxs)
            filtered_page_v1 = page.filter(filter_table)
            extracted_tables = filtered_page_v1.extract_tables(
                table_settings={"horizontal_strategy": "lines_strict"}
            )

            tables_bboxs = [table.bbox for table in tables]
            filter_text = partial(must_conserve_text, bboxes=tables_bboxs)
            filtered_page_v2 = filtered_page_v1.filter(filter_text)
            extracted_text = filtered_page_v2.extract_text()
            if page_number == 1:
                updated = get_update(extracted_text or "")
                document_hash = get_hash(pdf_path)

            page_content = {
                "document": Path(pdf_path).name,
                "sector": sector,
                "document_hash": document_hash,
                "updated": updated,
                "page": page_number,
                "titles": get_titles(page),
                "ingestion_version": INGESTION_VERSION,
                "text": extracted_text or "",
                "tables": extracted_tables,
            }
            full_content.append(page_content)

    return full_content


def get_hash(pdf_path):
    with open(pdf_path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def get_update(text):
    month_regex = rf"(?:{'|'.join(MONTHS.keys())})"
    pattern = rf"mises?\s+à\s+jour\s+en\s+({month_regex})\s+(\d{{4}})"
    update = re.search(pattern, text, re.IGNORECASE)
    if update is None:
        raise DocumentRejectedError("Date de mise à jour introuvable.")

    month_name = update.group(1).lower()
    year = update.group(2)
    month = MONTHS[month_name]
    return f"{year}-{month}"


def get_titles(page):
    words = page.extract_words(extra_attrs=["size", "non_stroking_color"])
    target_color = (1.0,)

    big_words = [
        w
        for w in words
        if w.get("non_stroking_color") == target_color and w.get("size") >= 12
    ]

    big_words.sort(key=lambda w: (round(w["top"]), w["x0"]))

    lines = []
    for w in big_words:
        if lines and abs(w["top"] - lines[-1]["top"]) < 2:
            lines[-1]["words"].append(w["text"])
        else:
            lines.append({"top": w["top"], "size": w["size"], "words": [w["text"]]})

    titles = []
    previous = None
    for line in lines:
        text = " ".join(line["words"])
        if previous and line["top"] - previous["top"] < previous["size"] * 2:
            titles[-1] += " " + text
        else:
            titles.append(text)
        previous = line

    return [t.replace("(suite)", "").strip() for t in titles]


def main():

    manifest_path = DATA_DIR / "manifest.json"
    with open(manifest_path, "r", encoding="utf-8") as f:
        files = json.load(f)
    pages = []
    rejection_log = []
    for file in files:
        if file["status"] == "active":
            path = DATA_DIR / "raw" / f"{file['file']}"
            try:
                file_content = extract_document(path, file["sector"])
                pages.extend(file_content)
            except DocumentRejectedError as e:
                rejection_log.append(
                    {
                        "document": file["file"],
                        "reason": str(e),
                        "rejected_at": datetime.now().isoformat(timespec="seconds"),
                    }
                )
    pages_path = DATA_DIR / "processed" / "pages.json"
    pages_path.parent.mkdir(parents=True, exist_ok=True)
    with open(pages_path, "w", encoding="utf-8") as f:
        json.dump(pages, f, ensure_ascii=False, indent=4)

    rejections_path = DATA_DIR / "rejections.json"
    with open(rejections_path, "w", encoding="utf-8") as f:
        json.dump(rejection_log, f, ensure_ascii=False, indent=4)


if __name__ == "__main__":
    main()
