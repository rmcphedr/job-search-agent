from src.applications.inspection import resolve_linkedin_apply_url
from src.applications.generic_form import parse_generic_application


HTML = """
<form aria-label="Job Application Form">
  <input type="file" name="resume" required>
  <input placeholder="Your Name" required>
  <input placeholder="Your Email" required>
  <input placeholder="Address" required>
  <input placeholder="Phone Number" required>
  <label><input type="radio" name="Eligible-to-Work-in-Canada" value="Yes">Yes</label>
  <label><input type="radio" name="Eligible-to-Work-in-Canada" value="No">No</label>
  <button type="submit">Submit</button>
</form>
"""


def test_generic_inspection_maps_simple_form() -> None:
    inspection = parse_generic_application(HTML, "https://www.oncoustics.com/careers-post/ml")
    assert inspection.provider == "generic_web_form"
    assert {field.field_key for field in inspection.fields} == {
        "resume", "your_name", "your_email", "address", "phone_number", "eligible_to_work_in_canada"
    }
    assert all(field.required for field in inspection.fields)
    assert inspection.application_url.startswith("https://www.oncoustics.com/")


def test_non_linkedin_url_is_not_resolved() -> None:
    url = "https://www.oncoustics.com/careers-post/ml"
    assert resolve_linkedin_apply_url(url) == url
