import os
import fitz
from pathlib import Path


PDF_DIR = Path(__file__).parent.parent / "docs" / "Face recognition papers"
MD_DIR = PDF_DIR / "md"
MD_DIR.mkdir(exist_ok=True)


def extract_text_from_pdf(pdf_path: Path) -> str:
    path_str = str(pdf_path.resolve())
    if os.name == 'nt' and not path_str.startswith('\\\\?\\'):
        path_str = '\\\\?\\' + path_str
    doc = fitz.open(path_str)
    pages = []

    for i, page in enumerate(doc):
        text = page.get_text("text")
        pages.append(f"\n\n<!-- Page {i + 1} -->\n\n{text}")

    doc.close()
    return "\n".join(pages)


def clean_text(text: str) -> str:
    lines = text.splitlines()
    cleaned = []

    for line in lines:
        line = line.strip()

        if not line:
            cleaned.append("")
            continue

        # bỏ page number đơn giản
        if line.isdigit():
            continue

        cleaned.append(line)

    return "\n".join(cleaned)


def convert_to_md_template(title: str, raw_text: str) -> str:
    return f"""# {title}

## 1. Paper Information

- Title: {title}
- Task:
- Model type:
- Year:

## 2. Raw Extracted Text

{raw_text}

## 3. Notes

### Problem

### Core Idea

### Architecture

### Dataset

### Metrics

### Strengths

### Weaknesses

### Relevance to Our Pipeline

### Implementation Notes

### Key Takeaways
"""


def safe_filename(stem: str, max_len: int = 80) -> str:
    """Truncate filename to avoid Windows MAX_PATH (260 chars) limit."""
    if len(stem) <= max_len:
        return stem
    return stem[:max_len].rstrip(". ")


def main():
    pdfs = list(PDF_DIR.glob("*.pdf"))
    print(f"Found {len(pdfs)} PDF files in {PDF_DIR}")
    
    success = 0
    for pdf_path in pdfs:
        short_name = safe_filename(pdf_path.stem)
        out_path = MD_DIR / f"{short_name}.md"
        
        print(f"Parsing {pdf_path.name}...")
        try:
            raw_text = extract_text_from_pdf(pdf_path)
            clean = clean_text(raw_text)

            title = pdf_path.stem.replace("_", " ").title()
            md = convert_to_md_template(title, clean)

            out_path.write_text(md, encoding="utf-8")

            print(f"  -> Saved to {out_path.name}")
            success += 1
        except Exception as e:
            print(f"  -> ERROR: {e}")

    print(f"\nDone! {success}/{len(pdfs)} files processed.")


if __name__ == "__main__":
    main()
