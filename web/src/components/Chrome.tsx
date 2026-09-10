/* Page furniture: the sticky header with the procedure switcher, and the footer. */
import type { ProcedureFixture } from "../fixtures";

export const REPO = "https://github.com/SAY-5/playbook";

export interface TopBarProps {
  fixtures: ProcedureFixture[];
  active: string;
  onSelect: (dir: string) => void;
}

export function TopBar({ fixtures, active, onSelect }: TopBarProps) {
  return (
    <header className="topbar">
      <div className="wrap topbar__inner">
        <a className="brand" href="#top">
          <span className="brand__mark" aria-hidden="true" />
          <span className="brand__name">Playbook</span>
        </a>
        <div className="seg" role="group" aria-label="procedure">
          {fixtures.map((f) => (
            <button key={f.dir} type="button" className="seg__btn" aria-pressed={active === f.dir} onClick={() => onSelect(f.dir)}>
              {f.label}
            </button>
          ))}
        </div>
        <a className="topbar__link" href={REPO} rel="noreferrer noopener">
          Source
        </a>
      </div>
    </header>
  );
}

const DOCS: [string, string][] = [
  ["README", `${REPO}#readme`],
  ["ARCHITECTURE", `${REPO}/blob/main/ARCHITECTURE.md`],
  ["CONTRIBUTING", `${REPO}/blob/main/CONTRIBUTING.md`],
  ["Terraform stack", `${REPO}/tree/main/deploy/terraform`],
  ["Procedures", `${REPO}/tree/main/procedures`],
];

export function Footer() {
  return (
    <footer className="footer" id="about">
      <div className="wrap footer__inner">
        <div>
          <h2 className="footer__title">Playbook</h2>
          <p className="footer__text">
            Expert SOP to deployed agent, with evals. The Python package runs the same pipeline
            against the Anthropic Messages API, Jira and Slack, stores traces in S3 with a DynamoDB
            index, and deploys the runner on AWS with Terraform. This page is the offline mode,
            ported to the browser: no backend, no network calls, no key.
          </p>
        </div>
        <nav className="footer__links" aria-label="repository">
          {DOCS.map(([label, href]) => (
            <a key={label} href={href} rel="noreferrer noopener">
              {label}
            </a>
          ))}
        </nav>
      </div>
    </footer>
  );
}
