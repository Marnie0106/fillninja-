"""LLM-backed summarization of project documents for grant discovery and form autofill."""

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
- For discovery: prefer concrete keywords (disciplines, methods, populations, geography, institution type).
- search_query_suggestions: 2–5 short web-search phrases for grants or programs (not full sentences). Include applicant type when known.
- summary: 2–4 sentences on what the project is and who is applying.
- For form autofill: copy values faithfully for the applicant facts fields (names, email, phone, addresses, institution, education, etc.). Lists can be short sentences.

Return one JSON object only: no markdown, no code fences, no text before or after."""


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
        "Do not submit unless the instructions above explicitly ask you to submit.):\n"
        f"{block}"
    )
    return [f.model_copy(update={"fill_task": (f.fill_task or "") + suffix}) for f in forms]


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
    return parsed
