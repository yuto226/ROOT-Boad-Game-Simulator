"""ルールブックPDF(docs/law-of-root-jpn.pdf)からテキストを抽出する。

docs/ はgit管理外のため、リポジトリを新環境に持っていった場合は
PDFを再取得してから本スクリプトで docs/rulebook_text/ を再生成する。

  PDF: https://arclightgames.jp/wp-content/uploads/2024/01/Law-of-Root_JPN-full-2023Dec.pdf
  依存: pip install pypdf

注意: PDFは2段組のため、抽出テキストはページ内で列の順序が
前後することがある(右列が先に出る等)。参照時は文意で補正すること。
"""
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent
PDF = ROOT / "docs" / "law-of-root-jpn.pdf"
OUT = ROOT / "docs" / "rulebook_text"


def main() -> None:
    reader = PdfReader(PDF)
    OUT.mkdir(parents=True, exist_ok=True)
    full = []
    for i, page in enumerate(reader.pages, 1):
        text = page.extract_text() or ""
        (OUT / f"page{i:02d}.txt").write_text(text)
        full.append(f"===== PAGE {i} =====\n{text}")
    (OUT / "full.txt").write_text("\n".join(full))
    print(f"{len(reader.pages)} pages -> {OUT}")


if __name__ == "__main__":
    main()
