import type { ReactNode } from "react";

export function StatusPlaceholder({ title, message }: { title: string; message: ReactNode }) {
  return (
    <div className="flex h-full flex-1 items-center justify-center bg-background-surface p-6 text-text-primary">
      <div className="w-full max-w-3xl border border-border-strong bg-background-elevated p-8 text-center">
        <div className="text-[10px] uppercase tracking-[0.14em] text-text-dim">{title}</div>
        <div className="mx-auto mt-5 max-w-2xl text-[15px] leading-7 text-text-primary">{message}</div>
      </div>
    </div>
  );
}