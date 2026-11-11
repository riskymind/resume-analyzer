"""Skill lexicon: canonical names, aliases and families of *related* (not equivalent) skills.

Plain, reviewable data. Rules:

- Aliases are true synonyms ("k8s" = Kubernetes, "Postgres" = PostgreSQL); an
  alias match counts as an exact match.
- A *family* groups skills that are related but not interchangeable (Django,
  Flask and FastAPI are all Python web frameworks). Sharing a family is
  reported as a related match and never as an exact one.
- ``ambiguous`` skills ("Go", "R", "Swift") are also ordinary English words or
  letters. They are matched only against explicit skill lists, never by
  searching free text, to avoid false positives like "ready to go".
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class SkillEntry:
    canonical: str
    aliases: tuple[str, ...] = ()
    family: str | None = None
    ambiguous: bool = False


def _e(canonical: str, *aliases: str, family: str | None = None, ambiguous: bool = False) -> SkillEntry:
    return SkillEntry(canonical, tuple(aliases), family, ambiguous)


SKILLS: tuple[SkillEntry, ...] = (
    # Programming languages (deliberately no family: Python is not "related" to Java for hiring purposes)
    _e("Python", "python3"),
    _e("Java"),
    _e("JavaScript", "js", "ecmascript", "es6", family="javascript"),
    _e("TypeScript", "ts", family="javascript"),
    _e("Go", "golang", ambiguous=True),
    _e("Rust"),
    _e("C++", "cpp"),
    _e("C#", "csharp", "c sharp", family="dotnet"),
    _e("C", ambiguous=True),
    _e("Ruby"),
    _e("PHP"),
    _e("Kotlin", family="jvm"),
    _e("Scala", family="jvm"),
    _e("Swift", ambiguous=True, family="ios"),
    _e("Objective-C", "objective c", family="ios"),
    _e("R", ambiguous=True),
    _e("SQL"),
    _e("Bash", "shell scripting"),
    _e("Elixir"),
    _e("Dart", family="mobile-cross"),
    # Web frameworks
    _e("Django", family="python-web"),
    _e("Flask", family="python-web"),
    _e("FastAPI", "fast api", family="python-web"),
    _e("Ruby on Rails", "ror", family="ruby-web"),
    _e("Spring Boot", "spring framework", family="java-web"),
    _e("ASP.NET", "asp.net core", family="dotnet"),
    _e(".NET", "dotnet", ".net core", family="dotnet"),
    _e("Node.js", "nodejs", "node js", family="js-backend"),
    _e("Express", "express.js", "expressjs", family="js-backend", ambiguous=True),
    _e("NestJS", "nest.js", family="js-backend"),
    _e("Laravel", family="php-web"),
    _e("React", "react.js", "reactjs", family="js-frontend"),
    _e("Next.js", "nextjs", family="js-frontend"),
    _e("Vue.js", "vue", "vuejs", family="js-frontend"),
    _e("Angular", "angularjs", family="js-frontend"),
    _e("Svelte", family="js-frontend"),
    _e("HTML", "html5", family="web-markup"),
    _e("CSS", "css3", family="web-markup"),
    _e("Tailwind CSS", "tailwind", family="web-markup"),
    _e("GraphQL", family="api-style"),
    _e("REST", "rest api", "rest apis", "restful", "restful apis", family="api-style", ambiguous=True),
    _e("gRPC", family="api-style"),
    # Mobile
    _e("iOS", family="ios"),
    _e("Android", family="android"),
    _e("React Native", family="mobile-cross"),
    _e("Flutter", family="mobile-cross"),
    # Databases
    _e("PostgreSQL", "postgres", "postgresql", "psql", family="sql-db"),
    _e("MySQL", family="sql-db"),
    _e("SQL Server", "mssql", "microsoft sql server", family="sql-db"),
    _e("Oracle Database", "oracle db", family="sql-db"),
    _e("SQLite", family="sql-db"),
    _e("MongoDB", "mongo", family="nosql-db"),
    _e("DynamoDB", family="nosql-db"),
    _e("Cassandra", family="nosql-db"),
    _e("Redis", family="cache"),
    _e("Memcached", family="cache"),
    _e("Elasticsearch", "elastic search", "opensearch", family="search"),
    _e("Snowflake", family="warehouse"),
    _e("BigQuery", family="warehouse"),
    _e("Redshift", family="warehouse"),
    # Cloud
    _e("AWS", "amazon web services", family="cloud"),
    _e("GCP", "google cloud", "google cloud platform", family="cloud"),
    _e("Azure", "microsoft azure", family="cloud"),
    _e("AWS Lambda", family="serverless"),
    _e("Cloud Functions", "google cloud functions", family="serverless"),
    # Containers / infrastructure
    _e("Docker", family="containers"),
    _e("Podman", family="containers"),
    _e("Kubernetes", "k8s", family="orchestration"),
    _e("Amazon ECS", "ecs", family="orchestration"),
    _e("Helm", family="orchestration"),
    _e("Terraform", family="iac"),
    _e("CloudFormation", "aws cloudformation", family="iac"),
    _e("Pulumi", family="iac"),
    _e("Ansible", family="config-mgmt"),
    _e("Chef", family="config-mgmt", ambiguous=True),
    _e("Puppet", family="config-mgmt"),
    _e("Linux", family="os"),
    _e("Nginx", family="web-server"),
    # CI/CD and tooling
    _e("CI/CD", "ci cd", "continuous integration", "continuous delivery", "continuous deployment"),
    _e("Jenkins", family="ci"),
    _e("GitHub Actions", family="ci"),
    _e("GitLab CI", "gitlab ci/cd", family="ci"),
    _e("CircleCI", family="ci"),
    _e("Git"),
    _e("Jira", family="tracking"),
    # Messaging / data
    _e("Kafka", "apache kafka", family="messaging"),
    _e("RabbitMQ", family="messaging"),
    _e("Amazon SQS", "sqs", family="messaging"),
    _e("Apache Spark", "spark", "pyspark", family="big-data"),
    _e("Hadoop", family="big-data"),
    _e("Airflow", "apache airflow", family="orchestration-data"),
    _e("dbt", family="orchestration-data"),
    _e("Pandas", family="python-data"),
    _e("NumPy", family="python-data"),
    # ML / AI
    _e("TensorFlow", family="ml-framework"),
    _e("PyTorch", family="ml-framework"),
    _e("scikit-learn", "sklearn", "scikit learn", family="ml-framework"),
    _e("Keras", family="ml-framework"),
    _e("Machine Learning", "ml", family="ml"),
    _e("Deep Learning", family="ml"),
    _e("NLP", "natural language processing", family="ml"),
    _e("LLMs", "llm", "large language models", family="ml"),
    # Observability / testing
    _e("Prometheus", family="observability"),
    _e("Grafana", family="observability"),
    _e("Datadog", family="observability"),
    _e("pytest", family="testing"),
    _e("Jest", family="testing"),
    _e("Cypress", family="testing"),
    _e("Selenium", family="testing"),
    _e("Playwright", family="testing"),
    # Practices
    _e("Microservices", "microservice architecture", family="architecture"),
    _e("Agile", "scrum", family="process"),
    _e("TDD", "test-driven development", family="testing-practice"),
)

# Sequences that may sit inside a term ("c++", "node.js", ".net", "ci/cd").
_TERM_CHARS = r"a-z0-9+#"


def normalize_term(text: str) -> str:
    """Comparison form for skill names: NFKC, lowercase, single spaces, no trailing punctuation."""

    text = unicodedata.normalize("NFKC", text).lower().strip()
    text = re.sub(r"[\u2010-\u2015\u2212]", "-", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" ,;:()[]\"'")


_BY_KEY: dict[str, SkillEntry] = {}
for _entry in SKILLS:
    for _key in (_entry.canonical, *_entry.aliases):
        _BY_KEY[normalize_term(_key)] = _entry


def lookup(term: str) -> SkillEntry | None:
    """The lexicon entry for ``term`` (canonical name or alias), if known."""

    key = normalize_term(term)
    entry = _BY_KEY.get(key)
    if entry is None:
        # "Python 3.12" -> "python"; "React 18" -> "react"
        stripped = re.sub(r"\s*v?\d+(?:\.\d+)*$", "", key)
        if stripped and stripped != key:
            entry = _BY_KEY.get(stripped)
    return entry


def canonical(term: str) -> str:
    """Canonical comparison key: the lexicon's canonical name if known, else the normalised term."""

    entry = lookup(term)
    return normalize_term(entry.canonical) if entry else normalize_term(term)


def surface_forms(term: str) -> tuple[str, ...]:
    """All normalised spellings that count as an exact mention of ``term``."""

    entry = lookup(term)
    if entry is None:
        return (normalize_term(term),)
    return tuple(dict.fromkeys(normalize_term(form) for form in (entry.canonical, *entry.aliases)))


def is_ambiguous(term: str) -> bool:
    entry = lookup(term)
    return bool(entry and entry.ambiguous)


def same_family(a: str, b: str) -> bool:
    """True when two *different* skills belong to the same family of related skills."""

    first, second = lookup(a), lookup(b)
    if first is None or second is None or first is second:
        return False
    return first.family is not None and first.family == second.family


def term_pattern(form: str) -> re.Pattern[str]:
    """Word-boundary-aware pattern for a normalised surface form inside normalised text."""

    escaped = re.escape(form).replace(r"\ ", r"[\s-]+")
    return re.compile(rf"(?<![{_TERM_CHARS}]){escaped}(?![{_TERM_CHARS}])")


def mentions(text_key: str, term: str, *, allow_ambiguous: bool = False) -> bool:
    """Whether normalised ``text_key`` mentions ``term`` or one of its aliases as a whole term."""

    if not allow_ambiguous and is_ambiguous(term):
        entry = lookup(term)
        # Unambiguous aliases ("golang") may still be searched.
        forms = [normalize_term(a) for a in entry.aliases] if entry else []
        return any(len(form) > 2 and term_pattern(form).search(text_key) for form in forms)
    return any(term_pattern(form).search(text_key) for form in surface_forms(term) if form)


def scan(text_key: str) -> list[SkillEntry]:
    """Lexicon skills mentioned in normalised text (ambiguous entries excluded), in lexicon order."""

    return [entry for entry in SKILLS if mentions(text_key, entry.canonical)]
