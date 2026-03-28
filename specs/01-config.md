# Spec 01: Client Configuration

## Purpose

Define the client config file that drives the entire pipeline. Everything client-specific lives here — nothing is hardcoded in the pipeline code. A new client = a new JSON file.

## Task

Create `src/config/rwe_client.json` containing:

### 1. Client identity

```json
{
  "client": {
    "name": "RWE Renewables",
    "full_name": "RWE AG",
    "sector": "Energy / Offshore Wind",
    "country": "United Kingdom"
  }
}
```

### 2. Projects

All current UK projects with status, capacity, key facts, and monitoring priority. Pull this from the build spec document (uploaded as `antml:document index 1`). Each project needs:
- name, capacity_mw, location, status, partners, key dates
- priority: `"HIGH PROFILE"`, `"MOST STRATEGICALLY IMPORTANT"`, `"STANDARD"`, `"MONITOR"`

Include: Sofia, Norfolk Vanguard East, Norfolk Vanguard West, Dogger Bank South, Awel y Môr, onshore wind portfolio, solar portfolio, gas/CCUS.

### 3. Keyword framework

200+ keywords organised by monitoring theme. Pull these from the monitoring briefing document (uploaded as `antml:document index 3`), sections 4.1-4.7. Structure:

```json
{
  "keywords": {
    "rwe_corporate": [...],
    "uk_energy_policy": [...],
    "offshore_wind": [...],
    "competitors": [...],
    "parliamentary": [...],
    "social_reputational": [...],
    "financial_investment": [...]
  }
}
```

Include the false positive avoidance rules from section 5.3 of the monitoring briefing.

### 4. Monitoring themes

Map to the report sections:

```json
{
  "monitoring_themes": [
    {"id": "policy_government", "label": "Policy & Government Activity", "section": "2.1"},
    {"id": "parliamentary", "label": "Parliamentary Activity", "section": "2.2"},
    {"id": "regulatory_legal", "label": "Regulatory & Legal", "section": "2.3"},
    {"id": "media_coverage", "label": "Media Coverage", "section": "2.4"},
    {"id": "social_media", "label": "Social Media & Digital", "section": "2.5"},
    {"id": "competitor_industry", "label": "Competitor & Industry Intelligence", "section": "2.6"},
    {"id": "stakeholder_third_party", "label": "Stakeholder & Third Party Activity", "section": "2.7"}
  ]
}
```

### 5. Escalation tiers

```json
{
  "escalation": {
    "IMMEDIATE": [
      "Any direct mention of RWE in Parliament",
      "Government announcements directly affecting RWE projects",
      "National media naming RWE",
      "Coordinated activism targeting RWE"
    ],
    "HIGH": [...],
    "STANDARD": [...]
  }
}
```

Pull the full definitions from the build spec.

### 6. Sources

List all sources with their access method:

```json
{
  "sources": {
    "programmatic": [
      {"name": "Hansard", "type": "api", "base_url": "https://hansard-api.parliament.uk"},
      {"name": "GOV.UK", "type": "api", "base_url": "https://www.gov.uk/api/search.json"}
    ],
    "web_search": [
      {"name": "Ofgem", "url": "https://www.ofgem.gov.uk"},
      {"name": "NESO", "url": "https://www.neso.energy"},
      {"name": "Crown Estate", "url": "https://www.thecrownestate.co.uk"},
      {"name": "Great British Energy", "url": "https://www.gbe.gov.uk"},
      {"name": "Planning Inspectorate", "url": "https://www.gov.uk/government/organisations/planning-inspectorate"}
    ],
    "media_specialist": ["Recharge News", "Windpower Monthly", "Utility Week", "Current±", "New Power"],
    "media_national": ["Financial Times", "The Times", "Bloomberg", "Reuters", "The Guardian", "The Telegraph", "BBC News"],
    "media_regional": ["Eastern Daily Press", "Grimsby Telegraph", "Northern Echo", "Daily Post"],
    "media_political": ["Politico London Playbook", "PoliticsHome"],
    "industry": ["RenewableUK", "Energy UK", "OEUK", "ORE Catapult", "Climate Change Committee"]
  }
}
```

### 7. Report template config

```json
{
  "report": {
    "consultancy_name": "WA Communications",
    "consultancy_subtitle": "Public Affairs & Strategic Communications",
    "classification": "CONFIDENTIAL",
    "prepared_by_default": "AI Monitoring Agent (Draft)",
    "reviewed_by_default": "[Account Lead]"
  }
}
```

## Acceptance criteria

- The config file is valid JSON.
- A second client config (even a stub) can be created by copying and modifying — no code changes needed.
- All keyword lists match the monitoring briefing document. Count them — there should be 200+.
- The pipeline code imports client config by path, never by hardcoded values.
