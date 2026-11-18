from pathlib import Path
import pymupdf
from PySide6.QtCore import QThread, Signal
from shared.conversion import ConversionWorker

class PDFSplitWorker(QThread):
    completed = Signal(str)
    failed = Signal(str)

    def __init__(self, source_path, output_dir):
        super().__init__()
        self.source_path = source_path
        self.output_dir = output_dir

    def run(self):
        source_path = Path(self.source_path)
        try:
            source = pymupdf.open(source_path)
            created = []
            try:
                if source.page_count < 1:
                    raise ValueError("This PDF has no pages to split.")
                for page_index in range(source.page_count):
                    page_pdf = pymupdf.open()
                    try:
                        page_pdf.insert_pdf(
                            source, from_page=page_index, to_page=page_index
                        )
                        destination = ConversionWorker._available_path(
                            Path(self.output_dir)
                            / f"{source_path.stem}_page_{page_index + 1:03d}.pdf"
                        )
                        page_pdf.save(str(destination))
                        created.append(destination)
                    finally:
                        page_pdf.close()
            finally:
                source.close()
            self.completed.emit(
                f"Split into {len(created)} PDF files in {self.output_dir}"
            )
        except Exception as error:
            self.failed.emit(str(error))

