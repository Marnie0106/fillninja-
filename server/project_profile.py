"""LLM-backed summarization of project documents for grant discovery and form autofill."""

import re
from typing import Any

from pydantic import BaseModel, Field

from autogen.beta import Agent, PromptedSchema

from server.discovery import DiscoveredForm
from server.json_util import parse_prompted_agent_reply
from server.llm import build_llm_config

MAX_CHARS_FOR_PROFILE = 28_000

PROFILE_SYSTEM = """You analyze project documents: research summaries, proposals, CVs, slide decks as plain text, nonprofit materials, startup decks, or text from a web page.
Your structured output is used for (1) finding funding opportunities and (2) filling real application forms with data taken only from this document.
The source may include a speech transcript from an uploaded video or from YouTube captions (spoken words only, no visual OCR).
Repository links may be resolved to GitHub README/raw text; treat that like other project prose.

Rules:
- Use only information that is clearly supported by the document text. If unknown, use an empty string or empty list. Never invent employers, degrees, IDs, or contact info.
- Résumés / CVs: read the header or contact block. When an email appears in the text (e.g. name@domain.com), you must copy it into the `email` field. Prefer the address in the header or explicitly labeled "Email" / "e-mail". Do not leave `email` empty when a clear address exists in the source.
- Same for `phone` when a clear phone number pattern exists in the contact section.
- For discovery: prefer concrete keywords (disciplines, methods, populations, geography, institution type).
- search_query_suggestions: 2–5 short web-search phrases for grants or programs (not full sentences). Include applicant type when known.
- summary: 2–4 sentences on what the project is and who is applying.
- For form autofill: copy values faithfully for the applicant facts fields (names, email, phone, addresses, institution, education, etc.). Lists can be short sentences.

Return one JSON object only: no markdown, no code fences, no text before or after."""


CONTACT_FOCUS_SYSTEM = """You extract ONLY identity and contact fields from document text (résumé, CV, cover letter header, or signature block).

Rules:
- Use only text explicitly present. Empty string for any field not clearly there. Never guess or normalize away details.
- email: copy the primary address exactly (e.g. user@domain.com). Prefer header or labeled contact lines.
- phone: copy one main number exactly as written (digits, spaces, parentheses as in source).
- full_legal_name: the applicant's full name when it clearly identifies them (often the CV title line).
- preferred_name: first name or the name they use if clearly distinct (otherwise empty).

Return one JSON object only matching the schema; no markdown, no code fences."""


class ContactSupplement(BaseModel):
    email: str = ""
    phone: str = ""
    full_legal_name: str = ""
    preferred_name: str = ""


class ProjectProfileSummary(BaseModel):
    summary: str = ""
    field_domain: str = ""
    applicant_type: str = ""
    geography: str = ""
    keywords: list[str] = Field(default_factory=list)
    funding_needs: str = ""
    search_query_suggestions: list[str] = Field(default_factory=list)

    full_legal_name: str = ""
    preferred_name: str = ""
    email: str = ""
    phone: str = ""
    mailing_address: str = ""
    date_of_birth_if_stated: str = ""
    citizenship_or_residency_if_stated: str = ""
    institution_or_employer: str = ""
    role_or_title: str = ""
    department_if_stated: str = ""
    program_or_major: str = ""
    degree_level_if_stated: str = ""
    project_title_if_stated: str = ""
    education_background: str = ""
    experience_or_employment_summary: str = ""
    identifiers_if_stated: str = ""
    other_facts_for_forms: str = ""


def build_profiler_agent(config: Any) -> Agent:
    return Agent(
        "project_profiler",
        prompt=[PROFILE_SYSTEM],
        config=config,
        response_schema=PromptedSchema(ProjectProfileSummary),
    )


def build_contact_supplement_agent(config: Any) -> Agent:
    return Agent(
        "contact_supplement",
        prompt=[CONTACT_FOCUS_SYSTEM],
        config=config,
        response_schema=PromptedSchema(ContactSupplement),
    )


def _merge_contact_supplement(
    profile: ProjectProfileSummary, supplement: ContactSupplement
) -> ProjectProfileSummary:
    updates: dict[str, str] = {}
    pairs: list[tuple[str, str, str]] = [
        ("email", profile.email, supplement.email),
        ("phone", profile.phone, supplement.phone),
        ("full_legal_name", profile.full_legal_name, supplement.full_legal_name),
        ("preferred_name", profile.preferred_name, supplement.preferred_name),
    ]
    for key, existing, extra in pairs:
        if (existing or "").strip():
            continue
        extra_stripped = (extra or "").strip()
        if extra_stripped:
            updates[key] = extra_stripped
    if not updates:
        return profile
    return profile.model_copy(update=updates)


async def augment_profile_contact_from_llm(
    document_text: str, profile: ProjectProfileSummary
) -> ProjectProfileSummary:
    """Second pass: focused extraction for identity/contact when the main profiler missed fields."""
    text = (document_text or "").strip()
    if not text:
        return profile
    config = build_llm_config()
    agent = build_contact_supplement_agent(config)
    reply = await agent.ask(
        "Extract identity and contact fields from this document text only.\n\n---\n\n" + text
    )
    parsed: ContactSupplement | None = await parse_prompted_agent_reply(
        reply, ContactSupplement
    )
    if parsed is None:
        return profile
    return _merge_contact_supplement(profile, parsed)


def format_discovery_objective(user_hints: str, profile: ProjectProfileSummary) -> str:
    blocks: list[str] = []
    if user_hints.strip():
        blocks.append(f"User goal / notes:\n{user_hints.strip()}")
    kw = ", ".join(profile.keywords[:24]) if profile.keywords else ""
    tail = (
        f"Summary: {profile.summary}\n"
        f"Domain / field: {profile.field_domain}\n"
        f"Applicant type: {profile.applicant_type}\n"
        f"Geography: {profile.geography}\n"
        f"Keywords: {kw}\n"
        f"Funding needs: {profile.funding_needs}"
    )
    blocks.append("From uploaded project document:\n" + tail)
    merged = "\n\n".join(blocks).strip()
    if len(merged) < 15:
        return (
            "Find relevant open funding opportunities (grants, fellowships, RFPs) that match "
            "the applicant and project described in the uploaded document."
        )
    return merged


def format_applicant_facts_for_planner(profile: ProjectProfileSummary) -> str:
    pairs: list[tuple[str, str]] = [
        ("Full legal name", profile.full_legal_name),
        ("Preferred / first name", profile.preferred_name),
        ("Email", profile.email),
        ("Phone", profile.phone),
        ("Mailing address", profile.mailing_address),
        ("Date of birth (if stated)", profile.date_of_birth_if_stated),
        ("Citizenship / residency / visa (if stated)", profile.citizenship_or_residency_if_stated),
        ("Institution or employer", profile.institution_or_employer),
        ("Role or title", profile.role_or_title),
        ("Department (if stated)", profile.department_if_stated),
        ("Program or major / field", profile.program_or_major),
        ("Degree level (if stated)", profile.degree_level_if_stated),
        ("Project or proposal title (if stated)", profile.project_title_if_stated),
        ("Education background", profile.education_background),
        ("Experience / employment (concise)", profile.experience_or_employment_summary),
        ("Identifiers (ORCID, student ID, etc., if stated)", profile.identifiers_if_stated),
        ("Other facts useful on forms", profile.other_facts_for_forms),
    ]
    lines = [f"- {label}: {val.strip()}" for label, val in pairs if val and str(val).strip()]
    return "\n".join(lines)


def format_profile_as_applicant_context(profile: ProjectProfileSummary) -> str:
    """Plain-text block for single-tab /agent/run when a document was just profiled."""
    facts = format_applicant_facts_for_planner(profile).strip()
    if facts:
        return facts
    s = (profile.summary or "").strip()
    if s:
        return (
            "Applicant / document summary (use when filling; do not invent beyond this):\n" + s
        )
    return ""


def enrich_discovered_forms_with_applicant_facts(
    forms: list[DiscoveredForm],
    profile: ProjectProfileSummary,
) -> list[DiscoveredForm]:
    block = format_applicant_facts_for_planner(profile)
    if not block.strip():
        return list(forms)
    suffix = (
        "\n\n---\nApplicant data extracted from the user's uploaded materials "
        "(use these exact strings in FILL actions when a visible field label, name, or placeholder "
        "clearly matches; map sensibly for close synonyms (e.g. \"E-mail\" -> email). "
        "Do not invent values. If a required field has no matching fact, use done=true with reasoning. "
        "Never click Submit/Apply/Send or other final-commit controls unless the instructions above explicitly ask you to submit.):\n"
        f"{block}"
    )
    return [f.model_copy(update={"fill_task": (f.fill_task or "") + suffix}) for f in forms]


_CONTACT_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9][a-zA-Z0-9._%+\-]*@[a-zA-Z0-9][a-zA-Z0-9.\-]*\.[a-zA-Z]{2,}",
    re.IGNORECASE,
)


def augment_profile_contact_from_text(
    document_text: str, profile: ProjectProfileSummary
) -> ProjectProfileSummary:
    """If the model left email empty, recover obvious addresses from raw text (e.g. PDF résumés)."""
    if (profile.email or "").strip():
        return profile
    head = document_text[:12000]
    m = _CONTACT_EMAIL_RE.search(head)
    if not m:
        m = _CONTACT_EMAIL_RE.search(document_text)
    if not m:
        return profile
    return profile.model_copy(update={"email": m.group(0).strip()})


async def summarize_document_for_grants(document_text: str) -> ProjectProfileSummary:
    text = (document_text or "").strip()
    if not text:
        raise ValueError("No text could be extracted from the document")
    if len(text) > MAX_CHARS_FOR_PROFILE:
        text = text[:MAX_CHARS_FOR_PROFILE] + "\n\n[... truncated ...]"

    config = build_llm_config()
    agent = build_profiler_agent(config)
    reply = await agent.ask(
        "Extract structured information from this document text for funding discovery and for "
        "autofill on application forms.\n\n---\n\n" + text
    )
    parsed: ProjectProfileSummary | None = await parse_prompted_agent_reply(
        reply, ProjectProfileSummary
    )
    if parsed is None:
        raise RuntimeError("Profiler returned empty content")
    with_contact = await augment_profile_contact_from_llm(text, parsed)
    return augment_profile_contact_from_text(text, with_contact)
