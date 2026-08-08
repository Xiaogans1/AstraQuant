interface RuntimeCardProps {
  label: string;
  value: string;
  detail?: string;
  tone?: "default" | "accent" | "warning";
}

export function RuntimeCard({
  label,
  value,
  detail,
  tone = "default",
}: RuntimeCardProps) {
  return (
    <article className="runtime-card" data-tone={tone}>
      <span className="runtime-card__label">{label}</span>
      <strong className="runtime-card__value">{value}</strong>
      {detail !== undefined ? (
        <span className="runtime-card__detail">{detail}</span>
      ) : null}
    </article>
  );
}
