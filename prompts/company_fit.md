You are evaluating how well a company matches a candidate's career profile.

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

## Company Information

Company Name: {company_name}
Industry: {industry}
Website: {website}
Career Page: {career_page}
Description: {description}
Specialties: {specialties}

## Scoring Dimensions

Score each dimension from 0 to 10:

- industry_alignment — alignment with AI, healthcare, biotech, neuroscience, or computational biology
- mission_alignment — alignment with scientific impact, healthcare innovation, or precision medicine
- career_alignment — availability and relevance of target roles for this candidate
- growth_potential — company growth, funding stage, and career advancement opportunity
- fit_score — overall weighted fit (not a simple average; weigh mission and career alignment heavily)

Also provide:

- reasoning — 2-4 sentence summary of the overall assessment
- best_roles — list of specific role titles at this company that best match the candidate
- interesting_factors — list of positive signals (tech stack, domain, research culture, etc.)
- red_flags — list of concerns or mismatches (empty list if none)
- confidence — 0 to 10 indicating how confident you are given available information

Return JSON ONLY with this exact structure:

{{
  "company_name": "<string>",
  "fit_score": <float 0-10>,
  "industry_alignment": <float 0-10>,
  "mission_alignment": <float 0-10>,
  "career_alignment": <float 0-10>,
  "growth_potential": <float 0-10>,
  "reasoning": "<string>",
  "best_roles": ["<string>"],
  "interesting_factors": ["<string>"],
  "red_flags": ["<string>"],
  "confidence": <float 0-10>
}}

No markdown. No explanation outside JSON.
