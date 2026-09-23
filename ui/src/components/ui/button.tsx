import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "../../lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md border text-sm font-semibold transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--hiqs-rust)] focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-45",
  {
    variants: {
      variant: {
        default: "border-[var(--hiqs-rust)] bg-[var(--hiqs-rust)] text-white shadow-[0_6px_16px_rgba(111,65,47,.14)] hover:bg-[var(--hiqs-rust-dark)]",
        outline: "border-[var(--hiqs-line)] bg-[var(--hiqs-paper)] text-[var(--hiqs-ink)] hover:border-[var(--hiqs-rust)] hover:bg-[var(--hiqs-paper-warm)] hover:shadow-[0_8px_20px_rgba(111,65,47,.12)]",
        ghost: "border-transparent bg-transparent text-[var(--hiqs-rust-dark)] hover:bg-[var(--hiqs-paper-warm)]",
      },
      size: {
        default: "h-10 px-4",
        sm: "h-8 px-3 text-xs",
        icon: "h-9 w-9 p-0",
      },
    },
    defaultVariants: { variant: "outline", size: "default" },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

export function Button({ className, variant, size, asChild = false, ...props }: ButtonProps) {
  const Component = asChild ? Slot : "button";
  return <Component className={cn(buttonVariants({ variant, size }), className)} {...props} />;
}

export { buttonVariants };
