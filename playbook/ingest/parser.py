"""Parse an SOP (numbered markdown) and a walkthrough transcript into a Procedure.

Every step, rule and decision point keeps a citation back to the file and line it came from so
that prompt text and eval failures can be traced to what the expert actually wrote or said.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from playbook.ingest.models import Citation, DecisionPoint, Procedure, Rule, Step

_STEP_RE = re.compile(
    r"^(?P<num>\d+)\.\s+(?P<title>.*?)(?:\s+\{#(?P<id>[\w-]+)\})?(?:\s+\(tool:\s*(?P<tool>[\w.]+)\))?\s*$"
)
_TRANSCRIPT_RE = re.compile(r"^\[(?P<ts>\d{1,2}:\d{2}(?::\d{2})?)\]\s+(?P<who>[^:]+):\s+(?P<text>.+)$")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
_STOPWORDS = {
    "the",
    "a",
    "an",
    "to",
    "of",
    "in",
    "and",
    "or",
    "is",
    "it",
    "for",
    "on",
    "with",
    "that",
    "this",
    "as",
    "be",
    "if",
    "when",
    "then",
    "we",
    "i",
    "you",
    "so",
    "at",
    "by",
    "from",
    "do",
    "not",
    "never",
    "always",
    "also",
    "one",
    "them",
    "they",
    "its",
    "their",
    "our",
    "get",
    "gets",
}
_DECISION_HINTS = ("if ", "when ", "unless ", "otherwise", "exception", "must", "always")
_FORBIDDEN_HINTS = ("never ", "do not ", "don't ", "must not ")
# A priority matrix stated in prose: "sev1 is Highest, sev2 is High" or "full outage is Highest".
_MATRIX_RE = re.compile(r"\b[\w-]+ is (?:highest|high|medium|low|lowest)\b")
_CHANNEL_RE = re.compile(r"#[\w-]+")
_POSTING_RE = re.compile(r"\b(?:post|posts|page|pages|announce|slack)\b")


def _is_decision(low: str) -> bool:
    """A sentence is a decision when it carries a conditional or states a priority matrix."""
    return any(h in low for h in _DECISION_HINTS) or _MATRIX_RE.search(low) is not None


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def procedure_slug(procedure_dir: Path) -> str:
    """The slug of the procedure in `<dir>/sop.md`, taken from its `# Name` heading."""
    sop = procedure_dir / "sop.md"
    for line in sop.read_text().splitlines():
        if line.startswith("# "):
            return slugify(line[2:].strip())
    raise ValueError(f"{sop.name}: missing '# <name>' heading")


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9#.-]+", text.lower()) if t not in _STOPWORDS and len(t) > 2}


def parse_sop(path: Path) -> Procedure:
    """Parse the SOP markdown. Sections: Preconditions, Steps, Escalation, Never, Checks."""
    lines = path.read_text().splitlines()
    source = path.name
    name = ""
    purpose = ""
    section = ""
    proc = Procedure(name="", slug="", purpose="", sources=[source])
    current: Step | None = None

    for lineno, raw in enumerate(lines, start=1):
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.startswith("# ") and not name:
            name = line[2:].strip()
            continue
        if line.lower().startswith("purpose:"):
            purpose = line.split(":", 1)[1].strip()
            continue
        if line.startswith("## "):
            section = line[3:].strip().lower()
            current = None
            continue
        cite = Citation(source, lineno)
        if section == "steps":
            m = _STEP_RE.match(line)
            if m:
                title = m.group("title").strip()
                current = Step(
                    id=m.group("id") or slugify(title),
                    index=int(m.group("num")),
                    title=title,
                    instruction="",
                    tool=m.group("tool"),
                    citation=cite,
                )
                proc.steps.append(current)
            elif current is not None:
                body = line.strip()
                if body.startswith("- "):
                    current.rules.append(Rule(body[2:].strip(), cite))
                else:
                    current.instruction = (current.instruction + " " + body).strip()
            continue
        if line.strip().startswith("- "):
            rule = Rule(line.strip()[2:].strip(), cite)
            if section == "preconditions":
                proc.preconditions.append(rule)
            elif section == "escalation":
                proc.escalation_rules.append(rule)
            elif section == "never":
                proc.forbidden.append(rule)
            elif section == "checks":
                proc.checks.append(rule)

    if not name:
        raise ValueError(f"{source}: missing '# <name>' heading")
    if not proc.steps:
        raise ValueError(f"{source}: no numbered steps found under '## Steps'")
    proc.name = name
    proc.slug = slugify(name)
    proc.purpose = purpose
    return proc


def _step_text(step: Step) -> str:
    return f"{step.title} {step.instruction} {step.tool or ''} " + " ".join(r.text for r in step.rules)


def _best_step(proc: Procedure, sentence: str) -> str | None:
    """The step a decision belongs to.

    In order: the step whose own text names a channel the sentence names; for a priority matrix,
    the step that sets the priority; for a sentence about posting or paging, the first step whose
    tool is `slack.post`; otherwise the step with the largest keyword overlap.
    """
    low = sentence.lower()
    channels = set(_CHANNEL_RE.findall(low))
    if channels:
        for step in proc.steps:
            if channels & set(_CHANNEL_RE.findall(_step_text(step).lower())):
                return step.id
    if _MATRIX_RE.search(low):
        for step in proc.steps:
            if "priority" in _step_text(step).lower():
                return step.id
    if channels or _POSTING_RE.search(low):
        for step in proc.steps:
            if step.tool == "slack.post":
                return step.id
    words = _tokens(sentence)
    best, best_score = None, 0
    for step in proc.steps:
        score = len(words & _tokens(_step_text(step)))
        if score > best_score:
            best, best_score = step.id, score
    return best


def parse_walkthrough(path: Path, proc: Procedure) -> list[DecisionPoint]:
    """Pull decisions and prohibitions out of the expert's transcript lines.

    Only lines spoken by the expert are used; interviewer questions are ignored. Narrative
    sentences that carry no conditional, priority matrix or prohibition are dropped.
    """
    source = path.name
    found: list[DecisionPoint] = []
    for lineno, raw in enumerate(path.read_text().splitlines(), start=1):
        m = _TRANSCRIPT_RE.match(raw.strip())
        if not m or m.group("who").strip().lower() != "expert":
            continue
        for sentence in _SENTENCE_RE.split(m.group("text").strip()):
            low = sentence.lower()
            if any(h in low for h in _FORBIDDEN_HINTS):
                kind = "forbidden"
            elif _is_decision(low):
                kind = "decision"
            else:
                continue
            found.append(
                DecisionPoint(
                    id=f"{kind[0]}{len(found) + 1}",
                    text=sentence.strip(),
                    citation=Citation(source, lineno),
                    step_id=_best_step(proc, sentence),
                    kind=kind,
                )
            )
    return found


def ingest_procedure(procedure_dir: Path) -> Procedure:
    """Ingest `<dir>/sop.md` plus `<dir>/walkthrough.md` (optional) into one Procedure."""
    sop = procedure_dir / "sop.md"
    proc = parse_sop(sop)
    walkthrough = procedure_dir / "walkthrough.md"
    if walkthrough.exists():
        proc.decision_points = parse_walkthrough(walkthrough, proc)
        proc.sources.append(walkthrough.name)
    return proc


def load_procedure(path: Path) -> Procedure:
    """Load a Procedure from an ingested `procedure.json`."""
    return Procedure.from_dict(json.loads(path.read_text()))


def write_procedure(proc: Procedure, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(proc.to_dict(), indent=2) + "\n")
    return out
