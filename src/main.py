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


def fill_merged(table):
    data = table.extract()
    cells = [row.cells for row in table.rows]
    col_starts = []
    for row in cells:
        for bbox in row:
            if bbox is not None:
                x0 = bbox[0]
                if x0 not in col_starts:
                    col_starts.append(x0)
    col_starts.sort()
    row_starts = []
    for row in cells:
        for bbox in row:
            if bbox is not None:
                x0 = bbox[1]
                if x0 not in row_starts:
                    row_starts.append(x0)
    row_starts.sort()

    for r in range(len(cells)):
        for c in range(len(cells[r])):
            if cells[r][c] is not None:
                continue

            left = cells[r][c - 1] if c > 0 else None
            if left and left[2] > col_starts[c] + 1:
                data[r][c] = data[r][c - 1]
                cells[r][c] = cells[r][c - 1]
                continue

            up = cells[r - 1][c] if r > 0 else None
            if up and up[3] > row_starts[r] + 1:
                data[r][c] = data[r - 1][c]
                cells[r][c] = cells[r - 1][c]
                continue

    return data


def clean(cell):
    text = " ".join((cell or "").split())
    return re.sub(r"(\d+(?:re|e))année", r"\1 année", text)


def table_to_text(table):

    headers = [clean(h) for h in table[0]]
    results = []
    for row in table[1:]:
        cells = [clean(c) for c in row]
        pairs = [f"{h} : {v}" for h, v in zip(headers[1:], cells[1:])]
        text = f"{cells[0]} : " + " ; ".join(pairs)
        results.append(text)

    return results


def extract_document(pdf_path, sector):
    full_content = []

    with pdfplumber.open(pdf_path) as pdf:
        current_subtitle = ""
        for page_number, page in enumerate(pdf.pages, start=1):
            tables = page.find_tables(
                table_settings={"horizontal_strategy": "lines_strict"}
            )
            bboxs = [table.rows[0].bbox for table in tables]
            filter_table = partial(must_conserve_table, bboxes=bboxs)
            filtered_page_v1 = page.filter(filter_table)
            extracted_tables = filtered_page_v1.find_tables(
                table_settings={"horizontal_strategy": "lines_strict"}
            )
            tables_content = []
            for table in extracted_tables:
                zone_before_table = filtered_page_v1.crop(
                    (0, 0, page.width, table.bbox[1])
                )
                text_before_table = zone_before_table.extract_text() or ""
                matches = re.findall(r"^[A-Z]\. .+$", text_before_table, re.MULTILINE)
                subtitle = matches[-1] if matches else current_subtitle
                tables_content.append(
                    {"context": subtitle, "rows": table_to_text(fill_merged(table))}
                )

            tables_bboxs = [table.bbox for table in tables]
            filter_text = partial(must_conserve_text, bboxes=tables_bboxs)
            filtered_page_v2 = filtered_page_v1.filter(filter_text)
            extracted_text = filtered_page_v2.extract_text()

            page_subtitles = re.findall(
                r"^[A-Z]\. .+$", extracted_text or "", re.MULTILINE
            )
            if page_subtitles:
                current_subtitle = page_subtitles[-1]

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
                "tables": tables_content,
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


def make_chunk_id(page, suffix):
    return f"{page['sector'].replace(' ', '-')}-p{page['page']}-{suffix}"


def split_page(page, current_section):
    titres = page["titles"]
    L = []
    base_metadata = {
        k: v for k, v in page.items() if k not in ("text", "titles", "tables")
    }
    texte_restant = re.sub(r"\s*\d+/\d+\s*$", "", page["text"])
    for t in titres:
        pattern = re.escape(t).replace(r"\ ", r"\s+")
        title_search = re.search(pattern, texte_restant)
        if title_search is None:
            raise ValueError(f"Titre introuvable : {t}")
        title_start = title_search.start()
        title_end = title_search.end()
        pre_title = texte_restant[:title_start].strip()
        post_title = texte_restant[title_end:]
        post_title = re.sub(r"^\s*\(suite\)", "", post_title)
        texte_restant = post_title.strip()
        if pre_title != "":
            L.append(
                {
                    "chunk_id": make_chunk_id(page, len(L) + 1),
                    **base_metadata,
                    "type": "text",
                    "section": current_section,
                    "text": pre_title,
                }
            )
        current_section = t
    if texte_restant != "":
        L.append(
            {
                "chunk_id": make_chunk_id(page, len(L) + 1),
                **base_metadata,
                "type": "text",
                "section": current_section,
                "text": texte_restant,
            }
        )
    for table_idx, table in enumerate(page.get("tables", []), start=1):
        rows_text = "\n".join(table["rows"])
        if table["context"]:
            table_content = f"{current_section} > {table['context']} :\n{rows_text}"
        else:
            table_content = f"{current_section} > " + rows_text

        L.append(
            {
                "chunk_id": make_chunk_id(page, f"t{table_idx}"),
                **base_metadata,
                "type": "table",
                "section": current_section,
                "text": table_content,
            }
        )
    return L, current_section


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

    with open(pages_path, "r", encoding="utf-8") as f:
        pages = json.load(f)

    current_section = None
    current_document = None
    chunks = []
    for page in pages:
        if current_document != page["document_hash"]:
            current_section = None
            current_document = page["document_hash"]
        page_chunks, current_section = split_page(page, current_section)
        chunks.extend(page_chunks)
    chunks_path = DATA_DIR / "processed" / "chunks.json"
    with open(chunks_path, "w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False, indent=4)


if __name__ == "__main__":
    main()
