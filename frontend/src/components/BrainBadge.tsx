export function BrainBadge({ version }: { version: string }) {
  const v2 = version === "v2";
  return (
    <span
      className="text-xs px-1.5 py-0.5 rounded font-medium bg-muted text-muted-foreground"
      title={v2 ? "Brain a due stadi (analyst + trader)" : "Brain monolitico (baseline)"}
    >
      brain {version}
    </span>
  );
}
