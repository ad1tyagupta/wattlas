type Props = { years: number[]; activeYear: number; onChange: (year: number) => void };

export function Timeline({ years, activeYear, onChange }: Props) {
  return (
    <footer className="timeline" aria-label="Analysis year">
      <div className="timeline-title"><span>Horizon</span><strong>{activeYear}</strong></div>
      <div className="year-track">
        {years.map((year) => (
          <button
            key={year}
            type="button"
            className={year === activeYear ? "year active" : "year"}
            aria-pressed={year === activeYear}
            onClick={() => onChange(year)}
          >
            <span className="year-tick" />
            {year}
          </button>
        ))}
      </div>
      <p className="timeline-note">Scores change by selected year; sources retain their own dates.</p>
    </footer>
  );
}
