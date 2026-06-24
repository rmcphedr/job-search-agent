You are evaluating how well a job posting matches a candidate's career profile.

## Candidate Profile

- Neuroscience PhD
- Mila Postdoctoral Researcher
- Machine Learning
- Bioinformatics
- Healthcare AI
- Precision Medicine
- Computational Neuroscience
- Python
- PyTorch
- scikit-learn
- Multimodal Data Analysis

## Target Roles

- Machine Learning Scientist
- AI Scientist
- Research Scientist
- Data Scientist
- Bioinformatician
- Computational Biologist
- Scientific Consultant

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
  "skills_match": ["<string>"],
  "skill_gaps": ["<string>"],
  "recommended_actions": ["<string>"],
  "why_fit": "<string>",
  "concerns": ["<string>"],
  "confidence": <float 0-10>
}}

No markdown. No explanation outside JSON.
