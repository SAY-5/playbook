/* Section shell: a numbered landmark with a title, a lede and one scroll-triggered reveal. */
import { motion } from "framer-motion";
import type { ReactNode } from "react";

export interface SectionProps {
  id: string;
  num: string;
  title: string;
  lede: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
}

export function Section({ id, num, title, lede, aside, children }: SectionProps) {
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
        <motion.div
          initial={{ opacity: 0, y: 18 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, amount: 0.12 }}
          transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
        >
          {children}
        </motion.div>
      </div>
    </section>
  );
}
