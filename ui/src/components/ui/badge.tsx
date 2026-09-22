import type { HTMLAttributes } from "react";
import { cn } from "../../lib/utils";

export function Badge({ className, ...props }: HTMLAttributes<HTMLSpanElement>) {
  return (
    <span
      className={cn(
        "inline-flex items-center border border-current/20 bg-white/55 px-1.5 py-0.5 text-[10px] font-bold leading-none",
        className,
      )}
      {...props}
    />
  );
}
