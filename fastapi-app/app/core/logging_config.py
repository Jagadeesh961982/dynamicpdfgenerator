import logging


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("pdf_pipeline.api").setLevel(logging.INFO)
