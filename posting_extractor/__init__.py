from .extractor import (
    ExtractedJob,
    GenericHtmlExtractor,
    UpworkExtractor,
    WelcomeToTheJungleExtractor,
    extract_job_posting,
    select_extractor,
)

__all__ = [
    "extract_job_posting",
    "select_extractor",
    "UpworkExtractor",
    "WelcomeToTheJungleExtractor",
    "GenericHtmlExtractor",
    "ExtractedJob",
]

__version__ = "0.1.0"
