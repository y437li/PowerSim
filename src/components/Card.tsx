import type { ReactNode } from "react";

interface CardProps {
  children: ReactNode;
  title?: string;
  className?: string;
}

/** Shared card container — wraps a content block with optional header title. */
export function Card({ children, title, className = "" }: CardProps) {
  return (
    <div className={`card ${className}`.trim()}>
      {title && <div className="card__title">{title}</div>}
      <div className="card__body">{children}</div>
    </div>
  );
}
