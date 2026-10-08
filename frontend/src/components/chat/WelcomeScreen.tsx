"use client";

import { CapabilityCard } from "@/lib/types";
import CapabilityCardComponent from "@/components/common/CapabilityCard";

const CARDS: CapabilityCard[] = [
  {
    icon: "📊",
    title: "生产齐套与缺料",
    description: "基于 MRP、库存、在途和生产计划识别缺料与停线风险",
    prompt: "查询当前工厂的 MRP 缺料和停线风险，并给出处置建议",
  },
  {
    icon: "🛒",
    title: "寻源与供应商定点",
    description: "对比报价、产能、交期和质量表现，辅助供应商定点",
    prompt: "帮我分析某个 RFQ 的供应商报价并给出定点建议",
  },
  {
    icon: "📦",
    title: "交付协同",
    description: "跟踪交付计划、延期、ASN 与供应商交付达成率",
    prompt: "查看当前交付延期风险和需要催交的物料",
  },
  {
    icon: "🔍",
    title: "供应商质量风险",
    description: "结合 PPAP、PPM、来料质量和产能识别供应风险",
    prompt: "查询供应商质量与供应风险，并列出需升级处理的事项",
  },
];

interface Props {
  onPromptClick: (prompt: string) => void;
}

export default function WelcomeScreen({ onPromptClick }: Props) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center px-8">
      <div className="max-w-2xl w-full text-center">
        {/* 标题 */}
        <h1 className="text-2xl font-bold text-gray-900 mb-2">
          AutoSupply Agent
        </h1>
        <p className="text-sm text-gray-500 mb-8">
          新能源车智采链
        </p>

        {/* 功能卡片 2x2 */}
        <div className="grid grid-cols-2 gap-4">
          {CARDS.map((card) => (
            <CapabilityCardComponent
              key={card.title}
              card={card}
              onClick={onPromptClick}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
