from .extractor import ExtractedJob, GenericHtmlExtractor, UpworkExtractor, extract_job_posting

__all__ = [
    "extract_job_posting",
    "UpworkExtractor",
    "GenericHtmlExtractor",
    "ExtractedJob",
]

__version__ = "0.1.0"
