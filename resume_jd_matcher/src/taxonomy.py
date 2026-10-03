"""Canonical skill taxonomy and matching.

One vocabulary, used by three consumers so that the three evaluation conditions
are scored against the same ruler:

* condition A (TF-IDF baseline) - the "exact keyword overlap" rule in PS section 4
* the offline stub - so an offline run needs no model and no network
* the fabrication check - what counts as a claimable skill

Matching is deliberately literal. This is the *non-AI* half of the comparison:
if a JD says "PyTorch" and a resume says "deep learning frameworks", a literal
rule sees no overlap and a semantic model should. That gap is the point of the
whole experiment, so it must not be papered over with fuzzy matching here.
"""

from __future__ import annotations

import re
from functools import lru_cache

# canonical name -> aliases as they appear in real text
SKILL_LEXICON: dict[str, tuple[str, ...]] = {
    # --- languages / general engineering -----------------------------------
    "Python": ("python",),
    "Java": ("java",),
    "JavaScript": ("javascript", "js", "es6"),
    "TypeScript": ("typescript", "ts"),
    "C++": ("c++", "cpp"),
    "C#": ("c#", "csharp", ".net"),
    "Go": ("golang", "go语言"),
    "R": ("r语言", "r programming"),
    "SQL": ("sql", "sql queries"),
    "Bash": ("bash", "shell scripting", "shell script"),
    "Git": ("git", "github", "gitlab", "version control"),
    "Linux": ("linux", "unix"),
    "Docker": ("docker", "containerisation", "containerization"),
    "Kubernetes": ("kubernetes", "k8s"),
    "CI/CD": ("ci/cd", "continuous integration", "cicd", "jenkins", "github actions"),
    "REST APIs": ("rest api", "restful", "rest apis"),
    "Microservices": ("microservice", "microservices"),
    "Unit Testing": ("unit test", "unit tests", "unit testing", "pytest", "junit"),
    "Agile": ("agile", "scrum", "kanban"),
    # --- data / analytics ---------------------------------------------------
    "Pandas": ("pandas",),
    "NumPy": ("numpy",),
    "Data Cleaning": ("data cleaning", "data wrangling", "data preprocessing"),
    "Data Visualisation": (
        "data visualisation",
        "data visualization",
        "tableau",
        "power bi",
        "powerbi",
        "matplotlib",
        "seaborn",
    ),
    "Statistics": ("statistics", "statistical analysis", "hypothesis testing"),
    "A/B Testing": ("a/b test", "a/b testing", "ab testing", "experimentation"),
    "Excel": ("excel", "spreadsheet"),
    "ETL": ("etl", "elt", "data pipeline", "airflow", "dbt"),
    "BigQuery": ("bigquery",),
    "Snowflake": ("snowflake",),
    "Dashboarding": ("dashboard", "dashboarding", "dashboards", "reporting suite"),
    # --- AI / ML ------------------------------------------------------------
    "Machine Learning": ("machine learning", "ml models", "supervised learning"),
    "Deep Learning": ("deep learning", "neural network", "neural networks"),
    "PyTorch": ("pytorch", "torch"),
    "TensorFlow": ("tensorflow", "keras"),
    "scikit-learn": ("scikit-learn", "scikit learn", "sklearn"),
    "NLP": ("nlp", "natural language processing", "text classification"),
    "Computer Vision": ("computer vision", "cv models", "image classification"),
    "LLM": ("llm", "llms", "large language model", "large language models"),
    "RAG": ("rag", "retrieval augmented generation", "retrieval-augmented generation"),
    "Prompt Engineering": ("prompt engineering", "prompt design"),
    "Vector Database": ("vector database", "vector db", "chroma", "faiss", "pinecone"),
    "MLOps": ("mlops", "model deployment", "model serving"),
    "Feature Engineering": ("feature engineering", "feature extraction"),
    "Model Evaluation": ("model evaluation", "cross-validation", "cross validation"),
    "Hugging Face": ("hugging face", "huggingface", "transformers library"),
    # --- product ------------------------------------------------------------
    "Product Roadmap": ("roadmap", "product roadmap", "product strategy"),
    "User Research": ("user research", "user interviews", "usability testing"),
    "Wireframing": ("wireframe", "wireframing", "prototype", "figma"),
    "Backlog Grooming": ("backlog", "user stories", "sprint planning"),
    "Stakeholder Management": ("stakeholder", "stakeholders", "cross-functional"),
    "Market Analysis": ("market analysis", "competitive analysis", "market research"),
    "Product Metrics": ("product metrics", "kpi", "kpis", "north star metric"),
    "Jira": ("jira", "confluence"),
}

# Academic credentials are deliberately NOT in SKILL_LEXICON. They are a
# different dimension, they are not scored by any evaluation condition, and
# leaving them in produced a leak: the resume line "Master of Science" was
# counted as a skill, so the generator's "rendered skills == declared skills"
# check failed. The prefill comparison handles the degree field on its own.
CREDENTIALS: tuple[str, ...] = (
    "Bachelor", "Master", "MSc", "BSc", "PhD", "Doctorate",
)

# Tokens too short or too ambiguous for plain substring scanning. Only C#
# survives this list: a bare "go" or "r" is overwhelmingly a verb or a letter
# in real text, and treating them as technologies produced false positives in
# early runs. Go is matched through "golang" only.
_SHORT_ALIASES = {"C#": ("c#",)}

_ALIAS_TO_CANONICAL: dict[str, str] = {}
for _canon, _aliases in SKILL_LEXICON.items():
    for _alias in _aliases:
        _ALIAS_TO_CANONICAL[_alias.lower()] = _canon

_TOKEN_RE = re.compile(r"[A-Za-z0-9\+#\./\-]+")


@lru_cache(maxsize=1)
def _long_alias_patterns() -> tuple[tuple[str, re.Pattern[str]], ...]:
    patterns: list[tuple[str, re.Pattern[str]]] = []
    for alias, canon in _ALIAS_TO_CANONICAL.items():
        if len(alias) < 3:
            continue
        # \b works for word-ish aliases; "c++" and "ci/cd" need looser edges
        left = r"(?<![A-Za-z0-9])"
        right = r"(?![A-Za-z0-9])"
        patterns.append((canon, re.compile(left + re.escape(alias) + right, re.I)))
    # longest alias first so "scikit-learn" wins over a shorter incidental hit
    return tuple(sorted(patterns, key=lambda p: -len(p[1].pattern)))


def normalise_skill(text: str) -> str:
    """Lowercase, collapse separators. Used when comparing two skill strings."""
    cleaned = re.sub(r"[^a-z0-9\+#]+", " ", text.lower()).strip()
    return re.sub(r"\s+", " ", cleaned)


def match_skills(text: str) -> set[str]:
    """Canonical skills literally present in `text`.

    Conservative by construction: a miss here is a real signal about lexical
    matching, not a bug to be tuned away.
    """
    if not text:
        return set()

    found: set[str] = set()
    for canon, pattern in _long_alias_patterns():
        if pattern.search(text):
            found.add(canon)

    tokens = {t.lower() for t in _TOKEN_RE.findall(text)}
    for canon, aliases in _SHORT_ALIASES.items():
        if any(alias in tokens for alias in aliases):
            # "R" and "Go" only count when they look like a technology mention.
            found.add(canon)

    # Deliberately NO hierarchy implications. An earlier revision added
    # "Machine Learning" whenever "Deep Learning" was present, and
    # "Bachelor Degree" whenever "Master Degree" was present. That made the
    # mapping non-injective, so a display string could never round-trip to
    # exactly one canonical skill - which the generator's contract check
    # caught immediately. The vocabulary now reports only what is literally
    # named, and any inference is left to the model, where it belongs.
    return found


def skill_overlap(candidate_skills: set[str], required_skills: set[str]) -> float:
    """Fraction of the JD's hard requirements the candidate's data evidences.

    Empty requirement set -> 0.0, not 1.0. A JD we failed to parse must not
    score as a perfect match.
    """
    if not required_skills:
        return 0.0
    return len(candidate_skills & required_skills) / len(required_skills)


def ordered_skills(skills: set[str], reference: list[str] | None = None) -> list[str]:
    """Stable ordering: follow `reference` when given, else alphabetical."""
    if reference:
        seen = [s for s in reference if s in skills]
        rest = sorted(skills - set(seen))
        return seen + rest
    return sorted(skills)


def canonicalise(value: str) -> str:
    """Map a free-text skill string onto a canonical name when possible."""
    alias = normalise_skill(value)
    if alias in _ALIAS_TO_CANONICAL:
        return _ALIAS_TO_CANONICAL[alias]
    for canon, aliases in SKILL_LEXICON.items():
        if alias in {normalise_skill(a) for a in aliases}:
            return canon

    # Models habitually write a skill with its acronym: "natural language
    # processing (NLP)". That is ONE skill spelled twice, not two skills, so it
    # has to resolve - the scorer counts an unresolved claim as a fabrication,
    # and this exact string was reported as one against a resume that states it
    # verbatim.
    #
    # The fallback only fires when the string names EXACTLY ONE canonical
    # skill. A genuine compound ("Machine Learning and Deep Learning") is left
    # verbatim, because silently picking one half would under-report a real
    # fabrication - the more expensive mistake of the two.
    found = {canon for canon, pattern in _long_alias_patterns() if pattern.search(value)}
    if len(found) == 1:
        return next(iter(found))
    return value.strip()


def has_lexical_support(claim: str, source_text: str, present: set[str] | None = None) -> bool:
    """Does `source_text` actually evidence the skill `claim`?

    This is the check behind the fabrication guard: a model may only attribute a
    skill to the candidate if the candidate's own text says so. Two ways to pass,
    and both are needed:

    1. `canonicalise(claim)` is in the source's canonical skill set. This is the
       common path and it is case/alias insensitive, so the model's "machine
       learning" is accepted against the source's "Machine Learning".
    2. The claim's normalised words appear as WHOLE WORDS in the normalised
       source. This catches real skills that sit outside SKILL_LEXICON, so an
       out-of-vocabulary but genuinely stated skill is not flagged. The boundary
       guard is not optional: a plain substring test matched "java" inside
       "javascript" and let a real hallucination through - the resume listed
       JavaScript, the model claimed Java, and the guard waved it past.

    The inverse matters more than either: a claim with NO support in the source
    (the model asserting TensorFlow for a candidate who never mentions it) fails
    both tests and is still caught. An earlier revision compared the model's raw
    strings against the canonical set with a plain set difference, which failed
    test 1 for every lower-cased claim - the guard then stripped the entire
    matched-skill list on every live call.
    """
    if not claim or not claim.strip():
        return False
    if present is None:
        present = match_skills(source_text)
    if canonicalise(claim) in present:
        return True
    needle = normalise_skill(claim)
    if not needle:
        return False
    haystack = normalise_skill(source_text)
    return bool(re.search(r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])", haystack))
