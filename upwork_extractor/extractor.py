"""
upwork_extractor.extractor
~~~~~~~~~~~~~~~~~~~~~~~~~~
Extracts structured job data from a saved Upwork job posting HTML file.

HOW TO SAVE THE FILE CORRECTLY
-------------------------------
Open the job posting in its own browser tab (not as a slide-over panel on the
Find Work page). The URL should look like:

    https://www.upwork.com/freelance-jobs/apply/<slug>_~0<uid>/

Save that page as HTML (File → Save Page As… → "Webpage, HTML Only").
If you save the Find Work page while the posting is open as an overlay, the
file will use a different Nuxt bundle and this tool will tell you so.

INTERNALS
---------
Upwork's job detail page is a Nuxt 3 application. All server-side state is
serialised into a single <script type="application/json"> tag using the
`devalue` format — a flat array where every dict/list value is an integer
index into that array, with special tagged lists for non-JSON types.

We deserialise the array back into a plain Python object graph, then walk the
known path:

    root → vuex → jobDetails → { job, buyer, sands, connects, applicants }
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONTRACTOR_TIER = {1: "Entry Level", 2: "Intermediate", 3: "Expert"}
JOB_TYPE = {1: "Fixed-price", 2: "Hourly"}

_DEVALUE_SPECIAL_TAGS = frozenset({
    "Reactive", "Set", "Map", "Date", "RegExp", "Error",
    "URL", "BigInt", "undefined", "NaN", "Infinity", "-Infinity", "-0",
})

_WRONG_FILE_ERROR = """\
Could not find Upwork job data in this HTML file.

This usually means the page was saved while the job was open as a slide-over
panel on the Find Work page, rather than as a standalone tab.

To fix this:
  1. Click the job title to open it in its own browser tab.
     (The URL should contain /freelance-jobs/apply/...)
  2. Save that page as HTML: File → Save Page As → "Webpage, HTML Only".
  3. Re-run this tool on the newly saved file.
"""


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class Budget:
    job_type: str                  # "Fixed-price" | "Hourly"
    hidden: bool
    currency: str = "USD"
    fixed_amount: float | None = None
    hourly_min: float | None = None
    hourly_max: float | None = None

    def display(self) -> str:
        if self.hidden:
            return "Hidden"
        if self.job_type == "Fixed-price" and self.fixed_amount is not None:
            return f"${self.fixed_amount:,.2f} {self.currency}"
        if self.job_type == "Hourly":
            if self.hourly_min and self.hourly_max:
                return f"${self.hourly_min:.2f}–${self.hourly_max:.2f}/hr {self.currency}"
            if self.hourly_min:
                return f"${self.hourly_min:.2f}+/hr {self.currency}"
        return "N/A"


@dataclass
class Skill:
    name: str
    relevance: str        # "MANDATORY" | "NICE_TO_HAVE" | …
    uid: str = ""
    is_free_text: bool = False


@dataclass
class ClientStats:
    location_city: str | None
    location_country: str | None
    payment_verified: bool
    rating: float | None
    review_count: int
    total_spent: float | None
    total_assignments: int
    active_assignments: int
    total_hours: float
    jobs_posted: int
    jobs_with_hires: int
    avg_hourly_rate: float | None
    member_since: str | None       # e.g. "Aug 17, 2016"

    def hire_rate(self) -> int | None:
        if self.jobs_posted and self.jobs_with_hires is not None:
            return round(self.jobs_with_hires / self.jobs_posted * 100)
        return None


@dataclass
class Activity:
    total_applicants: int
    total_hired: int
    total_interviewed: int
    invitations_sent: int
    bid_avg: float | None
    bid_min: float | None
    bid_max: float | None
    bid_currency: str = "USD"
    connects_required: int = 0


@dataclass
class Attachment:
    file_name: str
    size_bytes: int
    uri: str

    def size_display(self) -> str:
        kb = self.size_bytes / 1024
        return f"{kb / 1024:.1f} MB" if kb >= 1024 else f"{kb:.0f} KB"


@dataclass
class JobPosting:
    uid: str
    ciphertext: str
    title: str
    url: str
    category: str
    category_group: str
    occupation: str
    budget: Budget
    duration_label: str | None
    duration_weeks: int | None
    contractor_tier: str
    project_type: str
    is_contract_to_hire: bool
    positions: int
    description: str
    skills: list[Skill]
    questions: list[str]
    attachments: list[Attachment]
    client: ClientStats
    activity: Activity
    posted_on: str | None          # ISO datetime string
    qualifications: dict[str, Any] = field(default_factory=dict)

    def posted_on_display(self) -> str:
        if not self.posted_on:
            return "Unknown"
        try:
            dt = datetime.fromisoformat(self.posted_on.replace("Z", "+00:00"))
            return dt.strftime("%B %d, %Y")
        except ValueError:
            return self.posted_on

    def skills_by_relevance(self, relevance: str) -> list[str]:
        return [s.name for s in self.skills if s.relevance.upper() == relevance.upper()]

    def mandatory_skills(self) -> list[str]:
        return self.skills_by_relevance("MANDATORY")

    def nice_to_have_skills(self) -> list[str]:
        return self.skills_by_relevance("NICE_TO_HAVE")

    def all_skill_names(self) -> list[str]:
        return [s.name for s in self.skills]


# ---------------------------------------------------------------------------
# Devalue deserialiser
# ---------------------------------------------------------------------------

def _revive_devalue(data: list) -> Any:
    """
    Reconstruct a Python object from a devalue-encoded flat array.

    devalue (https://github.com/Rich-Harris/devalue) stores every value at a
    numbered index. Dicts and lists contain integer indices rather than inline
    values. Special JS types are tagged two-element lists, e.g.:
        ['Reactive', 3]
        ['Date', '2024-01-01T00:00:00.000Z']
    """
    cache: dict[int, Any] = {}

    def resolve(idx: int) -> Any:
        if idx in cache:
            return cache[idx]

        item = data[idx]

        if isinstance(item, dict):
            result: dict = {}
            cache[idx] = result          # register before recursing (handles cycles)
            for k, v in item.items():
                result[k] = resolve(v)
            return result

        if isinstance(item, list):
            if item and isinstance(item[0], str) and item[0] in _DEVALUE_SPECIAL_TAGS:
                tag = item[0]
                if tag == "Reactive":
                    resolved = resolve(item[1])
                    cache[idx] = resolved
                    return resolved
                if tag == "Date":
                    cache[idx] = item[1]  # keep as ISO string
                    return item[1]
                cache[idx] = None
                return None

            result_list: list = []
            cache[idx] = result_list
            for v in item:
                result_list.append(resolve(v))
            return result_list

        # Primitive: str, int, float, bool, None
        cache[idx] = item
        return item

    header = data[0]
    root_idx = header[1] if (isinstance(header, list) and header[0] == "Reactive") else 1
    return resolve(root_idx)


# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------

class UpworkExtractor:
    """
    Extract structured data from a saved Upwork job posting HTML file.

    Usage::

        job = UpworkExtractor.from_file("posting.html").extract()
        print(job.to_markdown())
        print(job.to_yaml())

    See module docstring for how to save the file correctly.
    """

    _PAYLOAD_RE = re.compile(
        r'<script[^>]+type=["\']application/json["\'][^>]*>(.*?)</script>',
        re.DOTALL,
    )

    def __init__(self, html: str):
        self._html = html
        self._state: dict | None = None

    @classmethod
    def from_file(cls, path: str | Path) -> "UpworkExtractor":
        return cls(Path(path).read_text(encoding="utf-8"))

    @classmethod
    def from_string(cls, html: str) -> "UpworkExtractor":
        return cls(html)

    # ------------------------------------------------------------------
    # State extraction
    # ------------------------------------------------------------------

    def _get_state(self) -> dict:
        if self._state is not None:
            return self._state

        for raw_json in self._PAYLOAD_RE.findall(self._html):
            try:
                flat = json.loads(raw_json)
            except json.JSONDecodeError:
                continue

            if not isinstance(flat, list):
                continue

            try:
                root = _revive_devalue(flat)
                # Confirm this is a job detail payload
                _ = root["vuex"]["jobDetails"]["job"]["uid"]
                self._state = root
                return self._state
            except (KeyError, TypeError, Exception):
                continue

        raise ValueError(_WRONG_FILE_ERROR)

    def _job_details(self) -> dict:
        return self._get_state()["vuex"]["jobDetails"]

    # ------------------------------------------------------------------
    # Field builders
    # ------------------------------------------------------------------

    def _build_budget(self, job: dict) -> Budget:
        job_type = JOB_TYPE.get(job.get("type", 1), "Fixed-price")
        budget_obj = job.get("budget") or {}
        extended = job.get("extendedBudgetInfo") or {}
        return Budget(
            job_type=job_type,
            hidden=job.get("hideBudget", False),
            currency=budget_obj.get("currencyCode", "USD"),
            fixed_amount=budget_obj.get("amount") if job_type == "Fixed-price" else None,
            hourly_min=extended.get("hourlyBudgetMin"),
            hourly_max=extended.get("hourlyBudgetMax"),
        )

    def _build_skills(self, sands: dict) -> list[Skill]:
        skills: list[Skill] = []
        seen: set[str] = set()

        for group in sands.get("ontologySkills", []):
            for child in group.get("children", []):
                name = child.get("name", "")
                if name and name not in seen:
                    skills.append(Skill(
                        name=name,
                        relevance=child.get("relevance", "MANDATORY"),
                        uid=child.get("uid", ""),
                        is_free_text=child.get("isFreeText", False),
                    ))
                    seen.add(name)

        for s in sands.get("additionalSkills", []):
            name = s.get("name", "")
            if name and name not in seen:
                skills.append(Skill(
                    name=name,
                    relevance=s.get("relevance", "MANDATORY"),
                    uid=s.get("uid", ""),
                    is_free_text=s.get("isFreeText", False),
                ))
                seen.add(name)

        return skills

    def _build_client(self, buyer: dict) -> ClientStats:
        stats = buyer.get("stats", {})
        loc = buyer.get("location", {})
        company = buyer.get("company", {})
        jobs = buyer.get("jobs", {})

        member_since = None
        if contract_date := company.get("contractDate"):
            try:
                dt = datetime.fromisoformat(contract_date.replace("Z", "+00:00"))
                member_since = dt.strftime("%b %d, %Y")
            except ValueError:
                member_since = contract_date

        return ClientStats(
            location_city=loc.get("city"),
            location_country=loc.get("country"),
            payment_verified=buyer.get("isPaymentMethodVerified", False),
            rating=stats.get("score"),
            review_count=stats.get("feedbackCount", 0),
            total_spent=stats.get("totalCharges", {}).get("amount"),
            total_assignments=stats.get("totalAssignments", 0),
            active_assignments=stats.get("activeAssignmentsCount", 0),
            total_hours=stats.get("hoursCount", 0.0),
            jobs_posted=jobs.get("postedCount", 0),
            jobs_with_hires=stats.get("totalJobsWithHires", 0),
            avg_hourly_rate=buyer.get("avgHourlyJobsRate", {}).get("amount"),
            member_since=member_since,
        )

    def _build_activity(self, job: dict, details: dict) -> Activity:
        ca = job.get("clientActivity", {})
        bids = details.get("applicants", {}).get("applicantsBidsStats", {})
        return Activity(
            total_applicants=ca.get("totalApplicants", 0),
            total_hired=ca.get("totalHired", 0),
            total_interviewed=ca.get("totalInvitedToInterview", 0),
            invitations_sent=ca.get("invitationsSent", 0),
            bid_avg=bids.get("avgRateBid", {}).get("amount"),
            bid_min=bids.get("minRateBid", {}).get("amount"),
            bid_max=bids.get("maxRateBid", {}).get("amount"),
            bid_currency=bids.get("avgRateBid", {}).get("currencyCode", "USD"),
            connects_required=details.get("connects", {}).get("requiredConnects", 0),
        )

    def _build_url(self, job: dict) -> str:
        cipher = job.get("ciphertext", "")
        slug = re.sub(r"[^\w\s-]", "", job.get("title", ""))
        slug = re.sub(r"[\s_]+", "-", slug.strip())[:80]
        return f"https://www.upwork.com/freelance-jobs/apply/{slug}_{cipher}/"

    def _project_type(self, job: dict) -> str:
        for seg in job.get("segmentationData", []):
            if label := seg.get("label"):
                return label
        return "N/A"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(self) -> "ExtractedJob":
        details = self._job_details()
        job = details["job"]
        sands = details.get("sands", {})

        posting = JobPosting(
            uid=job.get("uid", ""),
            ciphertext=job.get("ciphertext", ""),
            title=job.get("title", ""),
            url=self._build_url(job),
            category=job.get("category", {}).get("name", ""),
            category_group=job.get("categoryGroup", {}).get("name", ""),
            occupation=sands.get("occupation", {}).get("prefLabel", ""),
            budget=self._build_budget(job),
            duration_label=(
                job.get("durationLabel")
                or (job.get("engagementDuration") or {}).get("label")
            ),
            duration_weeks=(job.get("engagementDuration") or {}).get("weeks"),
            contractor_tier=CONTRACTOR_TIER.get(job.get("contractorTier", 0), "Any"),
            project_type=self._project_type(job),
            is_contract_to_hire=job.get("isContractToHire", False),
            positions=job.get("numberOfPositionsToHire", 1),
            description=job.get("description", ""),
            skills=self._build_skills(sands),
            questions=[
                q.get("question", "")
                for q in job.get("questions", [])
                if q.get("question")
            ],
            attachments=[
                Attachment(
                    file_name=a["fileName"],
                    size_bytes=a.get("length", 0),
                    uri=a.get("uri", ""),
                )
                for a in job.get("attachments", [])
            ],
            client=self._build_client(details["buyer"]),
            activity=self._build_activity(job, details),
            posted_on=job.get("postedOn"),
            qualifications=job.get("qualifications", {}),
        )

        return ExtractedJob(posting)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

class ExtractedJob:
    def __init__(self, posting: JobPosting):
        self.posting = posting

    def to_dict(self) -> dict[str, Any]:
        p = self.posting
        c = p.client
        a = p.activity

        location = None
        if c.location_city and c.location_country:
            location = f"{c.location_city}, {c.location_country}"
        elif c.location_country:
            location = c.location_country

        return {
            "uid": p.uid,
            "url": p.url,
            "title": p.title,
            "posted_on": p.posted_on_display(),
            "category": p.category,
            "category_group": p.category_group,
            "occupation": p.occupation,
            "budget": {
                "type": p.budget.job_type,
                "hidden": p.budget.hidden,
                "amount": p.budget.fixed_amount,
                "hourly_min": p.budget.hourly_min,
                "hourly_max": p.budget.hourly_max,
                "currency": p.budget.currency,
                "display": p.budget.display(),
            },
            "duration": {
                "label": p.duration_label,
                "weeks": p.duration_weeks,
            },
            "experience_level": p.contractor_tier,
            "project_type": p.project_type,
            "is_contract_to_hire": p.is_contract_to_hire,
            "positions": p.positions,
            "description": p.description,
            "skills": {
                "mandatory": p.mandatory_skills(),
                "nice_to_have": p.nice_to_have_skills(),
                "all": p.all_skill_names(),
            },
            "questions": p.questions,
            "attachments": [
                {
                    "file_name": att.file_name,
                    "size": att.size_display(),
                    "size_bytes": att.size_bytes,
                    "uri": att.uri,
                }
                for att in p.attachments
            ],
            "client": {
                "location": location,
                "payment_verified": c.payment_verified,
                "rating": c.rating,
                "review_count": c.review_count,
                "total_spent_usd": c.total_spent,
                "total_assignments": c.total_assignments,
                "active_assignments": c.active_assignments,
                "total_hours": c.total_hours,
                "jobs_posted": c.jobs_posted,
                "hire_rate_pct": c.hire_rate(),
                "avg_hourly_rate_paid": c.avg_hourly_rate,
                "member_since": c.member_since,
            },
            "activity": {
                "total_applicants": a.total_applicants,
                "total_hired": a.total_hired,
                "total_interviewed": a.total_interviewed,
                "invitations_sent": a.invitations_sent,
                "bid_avg": round(a.bid_avg, 2) if a.bid_avg is not None else None,
                "bid_min": a.bid_min,
                "bid_max": a.bid_max,
                "bid_currency": a.bid_currency,
                "connects_required": a.connects_required,
            },
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def to_yaml(self) -> str:
        try:
            import yaml
        except ImportError:
            raise RuntimeError("PyYAML is required: pip install pyyaml")
        return yaml.dump(
            self.to_dict(),
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )

    def to_markdown(self) -> str:
        p = self.posting
        c = p.client
        a = p.activity
        loc = self.to_dict()["client"]["location"]

        lines: list[str] = []

        lines += [f"# {p.title}", ""]
        lines += [
            f"**Posted:** {p.posted_on_display()}",
            f"**URL:** {p.url}",
            f"**Budget:** {p.budget.display()} ({p.budget.job_type})",
            f"**Duration:** {p.duration_label or 'N/A'}",
            f"**Experience level:** {p.contractor_tier}",
            f"**Project type:** {p.project_type}",
            f"**Category:** {p.category_group} → {p.category}",
        ]
        if p.is_contract_to_hire:
            lines.append("**Contract to hire:** Yes")
        if p.positions > 1:
            lines.append(f"**Positions:** {p.positions}")
        lines.append("")

        lines += ["---", "", "## Skills & Expertise", ""]
        mandatory = p.mandatory_skills()
        nth = p.nice_to_have_skills()
        if mandatory:
            lines.append(f"**Mandatory:** {', '.join(mandatory)}")
        if nth:
            lines.append(f"**Nice to have:** {', '.join(nth)}")
        if not mandatory and not nth:
            lines += [f"- {s}" for s in p.all_skill_names()]
        lines.append("")

        lines += ["---", "", "## Job Description", "", p.description.strip(), ""]

        if p.questions:
            lines += ["---", "", "## Screening Questions", ""]
            for i, q in enumerate(p.questions, 1):
                lines.append(f"{i}. {q}")
            lines.append("")

        if p.attachments:
            lines += ["---", "", "## Attachments", ""]
            for att in p.attachments:
                lines.append(f"- {att.file_name} ({att.size_display()})")
            lines.append("")

        lines += ["---", "", "## About the Client", ""]
        if loc:
            lines.append(f"**Location:** {loc}")
        if c.payment_verified:
            lines.append("**Payment:** Verified")
        if c.rating is not None:
            lines.append(f"**Rating:** {c.rating}/5 ({c.review_count} reviews)")
        if c.total_spent is not None:
            lines.append(f"**Total spent:** ${c.total_spent:,.2f}")
        lines.append(f"**Hires:** {c.total_assignments} total, {c.active_assignments} active")
        if c.hire_rate() is not None:
            lines.append(f"**Jobs:** {c.jobs_posted} posted, {c.hire_rate()}% hire rate")
        if c.avg_hourly_rate:
            lines.append(f"**Avg hourly rate paid:** ${c.avg_hourly_rate:.2f}/hr")
        if c.total_hours:
            lines.append(f"**Total hours:** {c.total_hours:,.0f}")
        if c.member_since:
            lines.append(f"**Member since:** {c.member_since}")
        lines.append("")

        lines += ["---", "", "## Activity", ""]
        lines.append(f"**Proposals:** {a.total_applicants}")
        if a.bid_avg is not None:
            lines.append(
                f"**Bid range:** ${a.bid_min:,.2f} – ${a.bid_max:,.2f}"
                f" (avg ${a.bid_avg:,.2f}) {a.bid_currency}"
            )
        if a.total_interviewed:
            lines.append(f"**Interviewing:** {a.total_interviewed}")
        if a.connects_required:
            lines.append(f"**Connects to apply:** {a.connects_required}")
        lines.append("")

        return "\n".join(lines)
