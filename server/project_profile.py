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

Rules:
- Use only information clearly supported by the document text. If unknown, use an empty string or empty list. Never invent employers, degrees, IDs, or contact info.
- Résumés / CVs: read the header or contact block. When an email appears in the text, copy it into the `email` field. Prefer the address in the header or explicitly labeled "Email" / "e-mail".
- Same for `phone` when a clear phone number pattern exists.
- For discovery: prefer concrete keywords (disciplines, methods, populations, geography, institution type).
- search_query_suggestions: 2–5 short web-search phrases for grants or programs. Include applicant type when known.
- summary: 2–4 sentences on what the project is and who is applying.
- For form autofill: copy values faithfully for the applicant facts fields.

Return one JSON object only: no markdown, no code fences, no text before or after."""

CONTACT_FOCUS_SYSTEM = """You extract ONLY identity and contact fields from document text.
Rules:
- Use only text explicitly present. Empty string for any field not clearly there.
- email: copy the primary address exactly. Prefer header or labeled contact lines.
- phone: copy one main number exactly as written.
- full_legal_name: the applicant's full name when clearly identified.
- preferred_name: first name or the name they use if clearly distinct.

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
    text = (document_text or "").strip()
    if not text:
        return profile
    config = build_llm_config()
    agent = build_contact_supplement_agent(config)
    reply = await agent.ask(
        "Extract identity and contact fields from this document text only.\n\n---\n\n" + text
    )
    parsed: ContactSupplement | None = await parse_prompted_agent_reply(reply, ContactSupplement)
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
        return "Find relevant open funding opportunities (grants, fellowships, RFPs) that match the applicant and project described in the uploaded document."
    return merged


def format_applicant_facts_for_planner(profile: ProjectProfileSummary) -> str:
    pairs: list[tuple[str, str]] = [
        ("Full legal name", profile.full_legal_name),
        ("Preferred / first name", profile.preferred_name),
        ("Email", profile.email),
        ("Phone", profile.phone),
        ("Mailing address", profile.mailing_address),
        ("Date of birth (if stated)", profile.date_of_birth_if_stated),
        ("Citizenship / residency (if stated)", profile.citizenship_or_residency_if_stated),
        ("Institution / employer", profile.institution_or_employer),
        ("Role / title", profile.role_or_title),
        ("Department (if stated)", profile.department_if_stated),
        ("Program / major", profile.program_or_major),
        ("Degree level (if stated)", profile.degree_level_if_stated),
        ("Project title (if stated)", profile.project_title_if_stated),
        ("Education background", profile.education_background),
        ("Experience / employment summary", profile.experience_or_employment_summary),
        ("Identifiers (if stated)", profile.identifiers_if_stated),
        ("Other facts for forms", profile.other_facts_for_forms),
    ]
    lines: list[str] = ["--- Applicant data extracted from your document (use as FILL values when labels match) ---"]
    for label, value in pairs:
        if (value or "").strip():
            lines.append(f"{label}: {value.strip()}")
    lines.append("--- End applicant data ---")
    return "\n".join(lines)


def enrich_discovered_forms_with_applicant_facts(
    forms: list[dict], profile: ProjectProfileSummary
) -> list[dict]:
    applicant_block = format_applicant_facts_for_planner(profile)
    enriched = []
    for f in forms:
        task = (f.get("fill_task") or "").strip()
        f["fill_task"] = f"{task}\n\n{applicant_block}" if task else applicant_block
        enriched.append(f)
    return enriched


async def summarize_document_for_grants(document_text: str) -> ProjectProfileSummary:
    text = (document_text or "").strip()[:MAX_CHARS_FOR_PROFILE]
    if not text:
        return ProjectProfileSummary()
    config = build_llm_config()
    agent = build_profiler_agent(config)
    reply = await agent.ask(
        "Analyze this project document and extract structured profile data.\n\n---\n\n" + text
    )
    profile: ProjectProfileSummary | None = await parse_prompted_agent_reply(reply, ProjectProfileSummary)
    if profile is None:
        return ProjectProfileSummary()
    profile = await augment_profile_contact_from_llm(text, profile)
    return profile
