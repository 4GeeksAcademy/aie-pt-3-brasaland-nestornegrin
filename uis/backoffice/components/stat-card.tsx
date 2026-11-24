type StatCardProps = {
  label: string;
  value: string | number;
  compact?: boolean;
};

export function StatCard({ label, value, compact = false }: StatCardProps) {
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-5 text-center shadow-sm">
      <p className={compact ? "text-2xl font-black text-red-800" : "text-3xl font-black text-red-800"}>
        {value}
      </p>
      <p className="mt-1 text-xs font-semibold uppercase tracking-wide text-zinc-500">{label}</p>
    </div>
  );
}