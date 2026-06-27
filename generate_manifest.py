"""
generate_manifest.py
====================
Drop a PDF into this folder, run this script, and it will automatically
generate a filled manifest .txt file ready for the inject_bookmarks.py script.

Usage:
    python generate_manifest.py
    python generate_manifest.py "English 7 - Unit 1.pdf"

Requirements:
    pip install pymupdf
"""

try:
    import fitz
except ImportError:
    import subprocess
    print("pymupdf not found — installing it now...")
    subprocess.check_call([__import__("sys").executable, "-m", "pip", "install", "pymupdf", "-q"])
    import fitz
    print("Done. Continuing...")
import os
import sys
import re
from datetime import date

TOC_MARKER     = "TABLE OF CONTENTS"
FRONT_KEYWORDS = ["PREFACE", "Preface"]
BACK_KEYWORDS  = ["Final Reflections", "Summary Recap", "Glossary",
                  "Appendix", "Answer Key", "References"]

# Named sub-unit sections that appear as breadcrumb headers on content pages
SUBUNIT_HEADERS = ["The Story Unfolds", "Pretest"]

# Lines to skip when parsing
SKIP_PATTERNS = [
    r"^(UNIT|Unit)\s+\d+$",
    r"^Chapter\s+\d+$",
    r"^Lesson\s+\d+$",
    r"^CHILDRENS",
    r"^PUBLISHING",
    r"^english\s+\d",
    r"^UNIT\s+\d+\s*\|",
    r"^Unit\s+\d+\s*\|",
    r"^Chapter\s+\d+\s*\|",
    r"^Lesson\s+\d+\s*\|",
]


def is_skip_line(line):
    for pat in SKIP_PATTERNS:
        if re.match(pat, line.strip(), re.IGNORECASE):
            return True
    return False


def pick_pdf(folder):
    pdfs = [f for f in os.listdir(folder) if f.lower().endswith(".pdf")]
    if not pdfs:
        print("No PDF files found in this folder.")
        sys.exit(1)
    if len(pdfs) == 1:
        print("Found: " + pdfs[0])
        return os.path.join(folder, pdfs[0])
    print("Multiple PDFs found:")
    for i, p in enumerate(pdfs, 1):
        print("  " + str(i) + ". " + p)
    choice = input("Enter number: ").strip()
    return os.path.join(folder, pdfs[int(choice) - 1])


def first_lines(text, n=8):
    return [l.strip() for l in text.split("\n") if l.strip()][:n]


def classify_page(lines, seen_subunits):
    combined = " ".join(lines)

    if TOC_MARKER in combined:
        return "toc", ""

    for kw in FRONT_KEYWORDS:
        if any(l.upper().startswith(kw.upper()) for l in lines[:3]):
            return "front", kw.title()

    for kw in BACK_KEYWORDS:
        if any(kw.lower() in l.lower() for l in lines[:3]):
            return "back", kw

    # Unit cover page: "UNIT X" or "Unit X" alone on a line
    for idx, l in enumerate(lines[:5]):
        m = re.match(r"^(UNIT|Unit)\s+(\d+)$", l.strip())
        if m:
            # Short label: "Unit 1"
            return "unit", "Unit " + m.group(2)

    # Named sub-unit sections (e.g. "The Story Unfolds") — first occurrence only
    for kw in SUBUNIT_HEADERS:
        if kw in combined and kw not in seen_subunits:
            seen_subunits.add(kw)
            return "subunit", kw

    # Chapter cover page: "Chapter X" alone on a line
    for idx, l in enumerate(lines[:5]):
        m = re.match(r"^Chapter\s+(\d+)$", l.strip())
        if m:
            # Short label: "Chapter 1"
            return "chapter", "Chapter " + m.group(1)

    # Lesson title page: "Lesson X" is first line
    if lines and re.match(r"^Lesson\s+(\d+)$", lines[0].strip()):
        m = re.match(r"^Lesson\s+(\d+)$", lines[0].strip())
        # Short label: "Lesson 1"
        return "lesson", "Lesson " + m.group(1)

    return "content", ""


def extract_cover_info(pdf_path):
    """
    Read page 1 (the cover) to extract grade level and count cover pages.
    Returns (grade_level_str, cover_page_count).
    """
    doc = fitz.open(pdf_path)
    cover_text = doc[0].get_text() if len(doc) > 0 else ""
    doc.close()

    grade = ""
    # Look for patterns like "Grade 7", "grade 7", "Grade VII"
    m = re.search(r"[Gg]rade\s+(\d+|[IVX]+)", cover_text)
    if m:
        grade = "Grade " + m.group(1)

    # Determine how many pages are "cover" (pages before any real content).
    # For now we assume exactly 1 cover page; adjust if books differ.
    cover_count = 1
    return grade, cover_count


def extract_structure(pdf_path, page_offset=0):
    """
    Walk the PDF and collect section boundaries.
    page_offset is subtracted from every raw PDF page number so that
    page numbering in the manifest starts from 1 at the first real page.
    """
    doc = fitz.open(pdf_path)
    total = len(doc)
    sections = []
    toc_start = None
    seen_back     = set()
    seen_subunits = set()

    for i in range(total):
        # Skip cover pages entirely — they are not manifest entries
        if i < page_offset:
            continue

        text  = doc[i].get_text()
        lines = first_lines(text, 8)
        if not lines:
            continue

        level, label = classify_page(lines, seen_subunits)

        if level == "toc":
            if toc_start is None:
                toc_start = (i + 1) - page_offset
            continue

        if level == "back":
            if label in seen_back:
                continue
            seen_back.add(label)

        if level in ("unit", "subunit", "chapter", "lesson", "front", "back"):
            sections.append({"level": level, "label": label, "page": (i + 1) - page_offset})

    doc.close()

    if toc_start:
        toc_entry = {"level": "front", "label": "Table of Contents", "page": toc_start}
        insert_at = 0
        for j, s in enumerate(sections):
            if s["level"] == "front" and "preface" in s["label"].lower():
                insert_at = j + 1
                break
        sections.insert(insert_at, toc_entry)

    # Total pages available after offset
    return sections, total - page_offset


def compute_end_pages(sections, total_pages):
    """
    Compute end pages hierarchically so chapter ranges span all their lessons.

    Rules:
      - unit    ends at: page before next unit (or end of doc)
      - subunit ends at: page before next chapter or unit
      - chapter ends at: page before next chapter or unit
      - lesson  ends at: page before next lesson, chapter, or unit
      - front/back end at: page before the next section of any type
    """
    # Which levels "close" a given level
    CLOSES = {
        "unit":    {"unit", "back"},
        "subunit": {"chapter", "unit"},
        "chapter": {"chapter", "unit"},
        "lesson":  {"lesson", "chapter", "unit"},
        "front":   {"unit", "chapter", "lesson", "front", "back"},
        "back":    {"unit", "chapter", "lesson", "front", "back"},
    }

    for idx, sec in enumerate(sections):
        closes = CLOSES.get(sec["level"], set())
        end = total_pages  # default: end of document
        for j in range(idx + 1, len(sections)):
            if sections[j]["level"] in closes:
                end = sections[j]["page"] - 1
                break
        sec["end"] = end

    return sections


def build_manifest(sections, total_pages, pdf_name, author, grade_level=""):
    today = date.today().strftime("%B %d, %Y")
    title = os.path.splitext(pdf_name)[0]
    grade_str = grade_level if grade_level else "[Grade -- fill in]"

    lines = [
        "# ============================================================",
        "# Manifest: " + title,
        "# Grade Level: " + grade_str,
        "# School Year: SY 2026-2027",
        "# Authored by: " + author,
        "# Date: " + today,
        "# ============================================================",
        "",
    ]

    sections = compute_end_pages(sections, total_pages)

    level_map = {
        "front":   "-",
        "back":    "-",
        "unit":    "-",
        "subunit": "--",
        "chapter": "--",
        "lesson":  "---",
    }

    for sec in sections:
        dash  = level_map.get(sec["level"], "-")
        start = sec["page"]
        stop  = sec["end"]
        label = sec["label"]
        if start == stop:
            page_str = "(page " + str(start) + ")"
        else:
            page_str = "(page " + str(start) + " - " + str(stop) + ")"
        lines.append(dash + " " + label + " " + page_str)

    lines.append("")
    return "\n".join(lines)


def suggested_filename(pdf_name):
    base = os.path.splitext(pdf_name)[0]
    slug = re.sub(r"\s*-\s*", "-", base)
    slug = re.sub(r"\s+", "", slug)
    slug = slug.lower()
    return "manifest_" + slug + ".txt"


def main():
    folder = os.path.dirname(os.path.abspath(__file__))

    if len(sys.argv) > 1:
        pdf_path = sys.argv[1]
        if not os.path.isabs(pdf_path):
            pdf_path = os.path.join(folder, pdf_path)
    else:
        pdf_path = pick_pdf(folder)

    pdf_name = os.path.basename(pdf_path)
    print("Reading: " + pdf_name)

    author = input("Your name (for the header): ").strip() or "[Your Name]"

    print("Scanning pages...")
    grade_level, cover_count = extract_cover_info(pdf_path)
    if grade_level:
        print("Detected grade: " + grade_level)
    sections, total = extract_structure(pdf_path, page_offset=cover_count)
    sections = compute_end_pages(sections, total)
    print("Found " + str(len(sections)) + " sections across " + str(total) + " pages (cover excluded).")
    print()

    indent_map = {
        "front": "", "back": "", "unit": "",
        "subunit": "  ", "chapter": "  ", "lesson": "    "
    }
    for s in sections:
        ind = indent_map.get(s["level"], "")
        lvl = s["level"].upper().ljust(7)
        print("  " + ind + "[" + lvl + "] p." + str(s["page"]).rjust(3) + " - " + str(s["end"]).rjust(3) + "  " + s["label"])

    print()
    manifest_text = build_manifest(sections, total, pdf_name, author, grade_level)

    out_name = suggested_filename(pdf_name)
    out_path = os.path.join(folder, out_name)

    if os.path.exists(out_path):
        ow = input("  " + out_name + " already exists. Overwrite? (y/n): ").strip().lower()
        if ow != "y":
            out_name = input("Enter a new filename (.txt): ").strip()
            out_path = os.path.join(folder, out_name)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(manifest_text)

    print()
    print("Saved: " + out_path)
    print("Done! Review the file and fill in any [placeholders] before handing off to QA lead.")


if __name__ == "__main__":
    main()
