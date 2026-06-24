You are cleaning and structuring a scraped job posting for a candidate-facing job search dashboard.

## Input

Company: {company_name}
Job Title: {job_title}
Geographic Location: {location}
Work Location Type: {location_type}

Raw scraped text:
{raw_description}

## Task

Distill the raw text into a clean, readable job posting. Remove navigation links, footer text, donation prompts, social media links, legal boilerplate, duplicate headings, template placeholders, and other irrelevant content.

Return JSON ONLY with this exact structure:

{{
  "formatted_description": "<string>"
}}

The formatted_description must use plain text with these section headers when the content exists:

Location: <geographic location only, e.g. San Francisco, CA>
Work Location Type: <Remote, Hybrid, or On-Site when known>
Job Description:
<paragraphs>

Qualifications:
<bullet-style lines using '- ' prefix>

Preferred Qualifications:
<bullet-style lines using '- ' prefix, if present>

Benefits:
<bullet-style lines using '- ', if present>

Rules:
- Preserve factual job content only.
- Do not invent requirements or benefits not supported by the raw text.
- Use complete sentences and normal punctuation.
- Do not include URLs unless they are essential to applying.
- If a section is missing from the source, omit that section entirely.
- Keep the total output under 4000 characters when possible.
