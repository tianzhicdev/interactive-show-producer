import { cn } from "@/lib/cn";

export function ProgressBar({
  percent,
  className,
  showLabel = false,
  size = "sm",
}: {
  percent: number;
  className?: string;
  showLabel?: boolean;
  size?: "sm" | "md" | "lg";
}) {
  const clamped = Math.min(100, Math.max(0, percent));
  const heights = { sm: "h-1.5", md: "h-2.5", lg: "h-4" };

  return (
    <div className={cn("flex items-center gap-2", className)}>
      <div className={cn("flex-1 bg-gray-100 rounded-full overflow-hidden", heights[size])}>
        <div
          className="h-full bg-red-400 rounded-full transition-all duration-500 ease-out"
          style={{ width: `${clamped}%` }}
        />
      </div>
      {showLabel && (
        <span className="text-xs text-gray-500 tabular-nums w-10 text-right shrink-0">
          {Math.round(clamped)}%
        </span>
      )}
    </div>
  );
}
