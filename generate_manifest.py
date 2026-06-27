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

import fitz
import os
import sys
import re
from datetime import date

TOC_MARKER     = "TABLE OF CONTENTS"
FRONT_KEYWORDS = ["PREFACE", "Preface"]
BACK_KEYWORDS  = ["Final Reflections", "Summary Recap", "Glossary",
                  "Appendix", "Answer Key", "References"]

# Lines to skip when extracting clean titles
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

# Named sub-unit sections that appear as breadcrumb headers on content pages
SUBUNIT_HEADERS = ["The Story Unfolds", "Pretest"]


def is_skip_line(line):
    for pat in SKIP_PATTERNS:
        if re.match(pat, line.strip(), re.IGNORECASE):
            return True
    return False


def join_title_lines(lines):
    parts = []
    for l in lines:
        if not l or is_skip_line(l):
            break
        if len(l) > 60:
            break
        parts.append(l)
    return " ".join(parts).strip()


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
            unit_num = m.group(2)
            before = [p for p in lines[:idx] if not is_skip_line(p)]
            title = join_title_lines(before)
            label = "Unit " + unit_num + (": " + title if title else "")
            return "unit", label

    # Named sub-unit sections (e.g. "The Story Unfolds") — catch first occurrence only
    for kw in SUBUNIT_HEADERS:
        if kw in combined and kw not in seen_subunits:
            seen_subunits.add(kw)
            return "subunit", kw

    # Chapter cover page: "Chapter X" alone on a line
    for idx, l in enumerate(lines[:5]):
        m = re.match(r"^Chapter\s+(\d+)$", l.strip())
        if m:
            ch_num = m.group(1)
            before = [p for p in lines[:idx] if not is_skip_line(p)]
            title = join_title_lines(before)
            label = "Chapter " + ch_num + (": " + title if title else "")
            return "chapter", label

    # Lesson title page: "Lesson X" is first line
    if lines and re.match(r"^Lesson\s+(\d+)$", lines[0].strip()):
        m = re.match(r"^Lesson\s+(\d+)$", lines[0].strip())
        les_num = m.group(1)
        after = [p for p in lines[1:] if not is_skip_line(p) and len(p) > 3]
        title = join_title_lines(after)
        label = "Lesson " + les_num + (": " + title if title else "")
        return "lesson", label

    return "content", ""


def extract_structure(pdf_path):
    doc = fitz.open(pdf_path)
    total = len(doc)
    sections = []
    toc_start = None
    seen_back    = set()
    seen_subunits = set()

    for i in range(total):
        text  = doc[i].get_text()
        lines = first_lines(text, 8)
        if not lines:
            continue

        level, label = classify_page(lines, seen_subunits)

        if level == "toc":
            if toc_start is None:
                toc_start = i + 1
            continue

        if level == "back":
            if label in seen_back:
                continue
            seen_back.add(label)

        if level in ("unit", "subunit", "chapter", "lesson", "front", "back"):
            sections.append({"level": level, "label": label, "page": i + 1})

    doc.close()

    if toc_start:
        toc_entry = {"level": "front", "label": "Table of Contents", "page": toc_start}
        insert_at = 0
        for j, s in enumerate(sections):
            if s["level"] == "front" and "preface" in s["label"].lower():
                insert_at = j + 1
                break
        sections.insert(insert_at, toc_entry)

    return sections, total


def build_manifest(sections, total_pages, pdf_name, author):
    today = date.today().strftime("%B %d, %Y")
    title = os.path.splitext(pdf_name)[0]

    lines = [
        "# ============================================================",
        "# Manifest: " + title,
        "# Grade Level: [Grade -- fill in]",
        "# School Year: SY 2026-2027",
        "# Authored by: " + author,
        "# Date: " + today,
        "# ============================================================",
        "",
    ]

    # Compute end pages
    for idx, sec in enumerate(sections):
        nxt = sections[idx + 1]["page"] - 1 if idx + 1 < len(sections) else total_pages
        sec["end"] = nxt

    # Dash levels:
    #   front / back / unit  -> -
    #   subunit / chapter    -> --
    #   lesson               -> ---
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
    sections, total = extract_structure(pdf_path)
    print("Found " + str(len(sections)) + " sections across " + str(total) + " pages.")
    print()

    indent_map = {
        "front": "", "back": "", "unit": "",
        "subunit": "  ", "chapter": "  ", "lesson": "    "
    }
    for s in sections:
        ind = indent_map.get(s["level"], "")
        lvl = s["level"].upper().ljust(7)
        print("  " + ind + "[" + lvl + "] p." + str(s["page"]).rjust(3) + "  " + s["label"])

    print()
    manifest_text = build_manifest(sections, total, pdf_name, author)

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
