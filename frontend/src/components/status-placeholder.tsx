import type { ReactNode } from "react";

export function StatusPlaceholder({ title, message }: { title: string; message: ReactNode }) {
  return (
    <div className="flex h-full flex-1 items-center justify-center bg-[#131722] p-6 text-[#D1D4DC]">
      <div className="w-full max-w-3xl border border-[#363A45] bg-[#1E222D] p-8 text-center">
        <div className="text-[10px] uppercase tracking-[0.14em] text-[#787B86]">{title}</div>
        <div className="mx-auto mt-5 max-w-2xl text-[15px] leading-7 text-[#D1D4DC]">{message}</div>
      </div>
    </div>
  );
}