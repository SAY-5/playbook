/* Port of playbook/evals/report.py: per-version reports, before/after comparison and the text table. */
import type { Comparison, Rubric, RunGrade, VersionReport } from "./types";

const r4 = (x: number): number => Math.round(x * 10000) / 10000;

export function buildReport(grades: RunGrade[], rubric: Rubric): VersionReport {
  if (!grades.length) throw new Error("no grades to report");
  const n = grades.length;
  const perCriterion: Record<string, number> = {};
  for (const c of rubric.criteria) {
    let passed = 0;
    for (const g of grades) for (const r of g.results) if (r.id === c.id && r.passed) passed++;
    perCriterion[c.id] = r4(passed / n);
  }
  const made = grades.reduce((s, g) => s + g.requiredActionsMade, 0);
  const total = grades.reduce((s, g) => s + g.requiredActionsTotal, 0) || 1;
  const passedCount = grades.filter((g) => g.passed).length;
  return {
    procedureSlug: grades[0].procedureSlug,
    promptVersion: grades[0].promptVersion,
    mode: grades[0].mode,
    scenarios: n,
    passed: passedCount,
    passRate: r4(passedCount / n),
    meanScore: r4(grades.reduce((s, g) => s + g.score, 0) / n),
    perCriterion,
    requiredActionCoverage: r4(made / total),
    forbiddenViolations: grades.reduce((s, g) => s + g.forbiddenViolations, 0),
    grades,
  };
}

export function compareReports(before: VersionReport, after: VersionReport): Comparison {
  const b = new Map(before.grades.map((g) => [g.scenarioId, g.passed]));
  const a = new Map(after.grades.map((g) => [g.scenarioId, g.passed]));
  const criterionDeltas: Record<string, number> = {};
  for (const [k, v] of Object.entries(before.perCriterion)) {
    criterionDeltas[k] = r4((after.perCriterion[k] ?? 0) - v);
  }
  return {
    before: before.promptVersion,
    after: after.promptVersion,
    passRateDelta: r4(after.passRate - before.passRate),
    criterionDeltas,
    newlyPassing: Array.from(a.entries())
      .filter(([s, p]) => p && !(b.get(s) ?? false))
      .map(([s]) => s)
      .sort(),
    newlyFailing: Array.from(a.entries())
      .filter(([s, p]) => !p && (b.get(s) ?? false))
      .map(([s]) => s)
      .sort(),
  };
}

/** Python's `f"{x:.1f}"`: round the double itself, half to even only on an exact tie.
 *
 * A double is an exact tie at one decimal only when it is an odd multiple of 0.25, so the test is
 * on the value rather than on a tolerance: 12.35 is not representable, and the double nearest it
 * sits below the tie, which is why Python prints 12.3 for it and not 12.4.
 */
function fixed1(v: number): string {
  const quarters = v * 4;
  if (Number.isInteger(quarters) && quarters % 2 !== 0) {
    const floor = Math.floor(v * 10);
    const even = floor % 2 === 0 ? floor : floor + 1;
    return (even / 10).toFixed(1);
  }
  return v.toFixed(1);
}

export function pct(x: number): string {
  return `${fixed1(x * 100)}%`;
}


export interface TableRow {
  metric: string;
  values: number[];
  delta: number | null;
  format: "pct" | "int";
  criterion: boolean;
}

/** The rows of the before/after table, one per metric and per criterion. */
export function tableRows(reports: VersionReport[]): TableRow[] {
  const sorted = [...reports].sort((x, y) => x.promptVersion - y.promptVersion);
  if (!sorted.length) return [];
  const rows: TableRow[] = [];
  const row = (metric: string, values: number[], format: "pct" | "int", criterion = false) => {
    rows.push({
      metric,
      values,
      delta: values.length > 1 ? values[values.length - 1] - values[0] : null,
      format,
      criterion,
    });
  };
  row("pass rate", sorted.map((r) => r.passRate), "pct");
  row("mean score", sorted.map((r) => r.meanScore), "pct");
  row("required-action coverage", sorted.map((r) => r.requiredActionCoverage), "pct");
  row("forbidden actions", sorted.map((r) => r.forbiddenViolations), "int");
  for (const crit of Object.keys(sorted[0].perCriterion)) {
    row(crit, sorted.map((r) => r.perCriterion[crit] ?? 0), "pct", true);
  }
  return rows;
}

function cell(v: number, format: "pct" | "int", signed = false): string {
  if (format === "int") return (signed && v >= 0 ? "+" : "") + String(Math.trunc(v));
  return (signed && v >= 0 ? "+" : "") + pct(v);
}

/** Render versions side by side exactly as the CLI prints them. */
export function formatTable(reports: VersionReport[]): string {
  if (!reports.length) return "(no reports)";
  const sorted = [...reports].sort((x, y) => x.promptVersion - y.promptVersion);
  const head = ["metric", ...sorted.map((r) => `v${r.promptVersion}`)];
  if (sorted.length > 1) head.push(`delta v${sorted[0].promptVersion} to v${sorted[sorted.length - 1].promptVersion}`);
  const rows = tableRows(sorted).map((r) => {
    const cells = [(r.criterion ? "  " : "") + r.metric, ...r.values.map((v) => cell(v, r.format))];
    if (r.delta !== null) cells.push(cell(r.delta, r.format, true));
    return cells;
  });
  const widths = head.map((_, i) => Math.max(...[head, ...rows].map((r) => r[i].length)));
  const line = "| " + head.map((h, i) => h.padEnd(widths[i])).join(" | ") + " |";
  const sep = "|" + widths.map((w) => "-".repeat(w + 2)).join("|") + "|";
  const body = rows.map((r) => "| " + r.map((c, i) => c.padEnd(widths[i])).join(" | ") + " |");
  const mode = Array.from(new Set(sorted.map((r) => r.mode))).sort().join(", ");
  const title = `${sorted[0].procedureSlug}: ${sorted[0].scenarios} scenarios, mode=${mode}`;
  return [title, line, sep, ...body].join("\n");
}
