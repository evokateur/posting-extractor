"""
upwork_extractor
~~~~~~~~~~~~~~~~
Extract structured job data from saved Upwork job posting HTML files.
"""

from .extractor import (
    UpworkExtractor,
    ExtractedJob,
    JobPosting,
    Budget,
    Skill,
    ClientStats,
    Activity,
    Attachment,
)

__all__ = [
    "UpworkExtractor",
    "ExtractedJob",
    "JobPosting",
    "Budget",
    "Skill",
    "ClientStats",
    "Activity",
    "Attachment",
]

__version__ = "0.1.0"
