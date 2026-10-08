"use client";

export default function Logo() {
  return (
    <div className="flex items-center gap-3 px-4 py-5">
      <div className="w-9 h-9 rounded-lg bg-[#2563EB] flex items-center justify-center">
        <span className="text-white font-bold text-sm">AS</span>
      </div>
      <div className="flex flex-col">
        <span className="text-sm font-semibold text-gray-900">AutoSupply</span>
        <span className="text-[11px] text-gray-400">Supply Chain Agent</span>
      </div>
    </div>
  );
}
