You are evaluating how well a job posting matches a candidate's career profile.

## Candidate Profile

{candidate_profile}

Classify each material requirement as confirmed evidence, transferable evidence,
active development area, genuine gap, or unverified claim. Unverified claims must
not increase the score. Do not present active development areas as established experience.

## Job Information

Job Title: {job_title}
Company: {company_name}
Location: {location}
Description: {description}

## Company Context

Industry: {industry}
Company Description: {company_description}

## Scoring Dimensions

Evaluate internally using these dimensions (0-10 each):

- Skill Match — overlap between required/preferred skills and candidate expertise
- Experience Match — alignment of seniority, domain, and research background
- Career Alignment — fit with target roles and long-term career goals
- Growth Opportunity — learning potential, scope, and career trajectory
- Overall Fit — fit_score from 0 to 10

Return JSON ONLY with this exact structure:

{{
  "job_title": "<string>",
  "company_name": "<string>",
  "fit_score": <float 0-10>,
  "salary": "<compensation exactly as posted, or null>",
  "seniority": "<brief level inferred from explicit title/experience requirements, or null>",
  "employment_type": "<full-time, part-time, contract, etc., or null>",
  "role_summary": ["<3-5 short bullets describing the work, not the company>"],
  "job_requirements": ["<material required qualification from the posting>"],
  "preferred_qualifications": ["<material preferred/good-to-have qualification>"],
  "qualification_assessment": [
    {
      "requirement": "<required or preferred qualification, stated once>",
      "status": "<match or gap>",
      "evidence": "<concise profile evidence or concise missing-evidence explanation>",
      "preferred": <true only for preferred/good-to-have items>
    }
  ],
  "skills_match": ["<string>"],
  "skill_gaps": ["<string>"],
  "recommended_actions": ["<string>"],
  "why_fit": "<string>",
  "concerns": ["<string>"],
  "confidence": <float 0-10>
}}

Keep `why_fit` to one or two brief sentences. Keep every list item concise and
specific. Base `role_summary` on responsibilities in the full job description.
If the description is unavailable, return an empty role_summary and low confidence.
Never invent salary, seniority, employment type, requirements, or preferences.
Use null or an empty list when the posting does not provide the information.
Include every material required and preferred qualification exactly once in
`qualification_assessment`. Mark transferable evidence as a match only when it
substantively satisfies the requirement; otherwise mark it as a gap. Do not
repeat qualification bullets in `skills_match` or `skill_gaps`.

No markdown. No explanation outside JSON.
