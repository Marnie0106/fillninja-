# Zhaoyang_C5-AG2_repo.md

**GitHub URL:** https://github.com/Marnie0106/fillninja-

**Tagline:** A 5-agent AG2 Beta pipeline that discovers application forms from the web, profiles the applicant from uploaded documents, and fills form fields step-by-step — with an optional Reviewer agent gating any submit actions.

**Track:** multi-agent 多智能体

---

## Agent Count: 5

| # | Name | Role |
|---|------|------|
| 1 | Search Curator | Discovers real application form URLs from live web search |
| 2 | Project Profiler | Extracts structured applicant data from PDF / DOCX / PPTX |
| 3 | Contact Supplement | Refines email, phone, and name fields (second-pass extraction) |
| 4 | Planner | Decides the next browser action: FILL / CLICK / SELECT / SCROLL |
| 5 | Reviewer | Approves or blocks actions — prevents accidental form submission |

## Quick Demo

```bash
git clone https://github.com/Marnie0106/fillninja-
cd fillninja-
pip install -r requirements.txt
cp .env.example .env   # add OPENROUTER_API_KEY
python -m uvicorn server.main:app --port 8000
# then: curl http://127.0.0.1:8000/health
```

## AG2 Beta Pattern Used

```python
from autogen.beta import Agent, PromptedSchema

agent = Agent("curator", prompt=[SYSTEM], config=config,
              response_schema=PromptedSchema(DiscoveryResult))
reply = await agent.ask(user_message)
result: DiscoveryResult = await reply.content()
```
