/* Section shell: a numbered landmark with a title, a lede and one scroll-triggered reveal. */
import type { ReactNode } from "react";
import { useReveal } from "../hooks/motion";

export interface SectionProps {
  id: string;
  num: string;
  title: string;
  lede: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
}

export function Section({ id, num, title, lede, aside, children }: SectionProps) {
  const [ref, seen] = useReveal<HTMLDivElement>();

  return (
    <section className="section" id={id} aria-labelledby={`${id}-title`}>
      <div className="wrap">
        <div className="section__head">
          <span className="section__num" aria-hidden="true">
            {num}
          </span>
          <div className="section__titlerow">
            <h2 className="section__title" id={`${id}-title`}>
              {title}
            </h2>
            {aside}
          </div>
          <p className="section__lede">{lede}</p>
        </div>
        <div className={`reveal${seen ? " reveal--in" : ""}`} ref={ref}>
          {children}
        </div>
      </div>
    </section>
  );
}
