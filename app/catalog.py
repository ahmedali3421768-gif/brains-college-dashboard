"""Programme catalog (two-level selection).

Single source of truth for the Programme Category → Course lists, used by the
public form, the admin "Create Application" form, and validation. Editing this
one dict updates every dropdown in the system.
"""

PROGRAMME_CATALOG = {
    "Short Courses": {
        "Digital Skills": [
            "YouTube Automation & Monetization",
            "Video Editing",
            "Adobe Premiere Pro",
            "Digital Marketing",
            "Freelancing Course",
            "E-Commerce + eBay",
            "SEO (Search Engine Optimization)",
            "Full Stack Graphic Designing",
            "UI/UX Designing",
            "Generative AI",
            "Agentic AI",
        ],
        "Software Development": [
            "MERN Stack",
            "Web Designing & Development",
            "React and MongoDB",
            "Java",
            "Android Application Course",
            "Cloud Computing",
            "Cyber Security",
        ],
        "Technical & Professional Courses": [
            "Mobile Repairing Course",
            "Laptop Repairing Course",
            "Computer Hardware Engineering",
            "AutoCAD 2D & 3D",
            "3D Max",
            "Peach Tree",
            "Quick Book",
            "Tally",
            "Robotics",
            "Computer Course for Beginners",
            "Spoken English",
            "IELTS",
            "A1 Visa Course",
        ],
        "Professional Training": [
            "CCTV Course",
            "Auto EFI Scanner Training",
            "Shopify",
        ],
        "Bundle Courses": [
            "6 in 1",
            "3 in 1",
        ],
    },
}

PROGRAMME_CATEGORIES = list(PROGRAMME_CATALOG.keys())


def all_courses_for(category: str) -> list[str]:
    """Flat list of course names valid for a category."""
    entry = PROGRAMME_CATALOG.get(category)
    if entry is None:
        return []
    if isinstance(entry, list):
        return list(entry)
    courses = []
    for group in entry.values():
        courses.extend(group)
    return courses


def is_valid_course(category: str, course: str) -> bool:
    return course in all_courses_for(category)


def catalog_for_frontend() -> dict:
    """Shape the catalog for the form: category → grouped or flat courses."""
    out = {}
    for cat, entry in PROGRAMME_CATALOG.items():
        if isinstance(entry, list):
            out[cat] = {"grouped": False, "courses": entry}
        else:
            out[cat] = {"grouped": True, "groups": entry}
    return out


# ── Lead / marketing source (Module 21) ──────────────────────────────────
LEAD_SOURCES = [
    "Instagram", "WhatsApp", "Facebook", "LinkedIn", "YouTube", "Others",
]
