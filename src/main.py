from functools import partial
from pathlib import Path

import pdfplumber


def is_inside(obj, bbox):
    return (
        obj["x0"]>=bbox[0]
        and obj["top"]>=bbox[1]
        and obj["x1"]<=bbox[2]
        and obj["bottom"]<=bbox[3]
    )

def must_conserve_table(obj, bboxes):
    if obj["object_type"] != "char":
        return True
    for bbox in bboxes:
        if is_inside(obj, bbox) and obj["non_stroking_color"]!=(1.0,):
            return False

    return True

def must_conserve_text(obj, bboxes):
    for bbox in bboxes:
        if is_inside(obj, bbox):
            return False
    return True

def extract_document(pdf_path):
    full_content = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):

            tables = page.find_tables(table_settings={"horizontal_strategy": "lines_strict"})
            bboxs = [table.rows[0].bbox for table in tables]
            filter_table = partial(must_conserve_table, bboxes=bboxs)
            filtered_page_v1 = page.filter(filter_table)
            extracted_tables = filtered_page_v1.extract_tables(table_settings={"horizontal_strategy": "lines_strict"})

            tables_bboxs = [table.bbox for table in tables]
            filter_text = partial(must_conserve_text, bboxes=tables_bboxs)
            filtered_page_v2 = filtered_page_v1.filter(filter_text)
            extracted_text = filtered_page_v2.extract_text()

            page_content = {
                "document": Path(pdf_path).name,
                "page": page_number,
                "text": extracted_text,
                "tables": extracted_tables
            }
            full_content.append(page_content)
    
    
    return full_content