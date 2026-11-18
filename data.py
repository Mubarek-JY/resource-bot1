"""Static data: departments, years, semesters, resource types.

The department `tag` is the hashtag label used in the channel caption and in
callback data (`dept:<tag>`). Keep the display order below: it is the order of
the buttons.
"""

# (display name, hashtag label)
DEPARTMENTS: list[tuple[str, str]] = [
    ("Architecture", "ARCH"),
    ("Biotechnology", "BIOTECH"),
    ("Civil Engineering", "Ceng"),
    ("Chemical Engineering", "Cheng"),
    ("Electrical & Computer Engineering", "eceng"),
    ("Electromechanical Engineering", "Emeng"),
    ("Environmental Engineering", "Enveng"),
    ("Food Science & Nutrition", "FSAN"),
    ("Geology", "GEO"),
    ("Industrial Chemistry", "InCh"),
    ("Mechanical Engineering", "Mech"),
    ("Mining Engineering", "Mieng"),
    ("Software Engineering", "Sweng"),
]

# tag -> display name
DEPARTMENTS_BY_TAG: dict[str, str] = {tag: name for name, tag in DEPARTMENTS}

YEARS: list[int] = [1, 2, 3, 4, 5]
SEMESTERS: list[int] = [1, 2]

# (callback code, display label, hashtag label)
TYPES: list[tuple[str, str, str]] = [
    ("mid", "Mid Exam", "MidExam"),
    ("final", "Final Exam", "FinalExam"),
    ("ppt", "PPT", "PPT"),
    ("reference", "Reference", "Reference"),
    ("module", "Module", "Module"),
]

# code -> (display label, hashtag label)
TYPES_BY_CODE: dict[str, tuple[str, str]] = {
    code: (label, tag) for code, label, tag in TYPES
}
