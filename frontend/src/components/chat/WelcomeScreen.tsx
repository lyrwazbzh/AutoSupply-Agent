"use client";

import { CapabilityCard } from "@/lib/types";
import CapabilityCardComponent from "@/components/common/CapabilityCard";
import QuickAccess from "./QuickAccess";

const CARDS: CapabilityCard[] = [
  {
    icon: "📊",
    title: "供应商分析",
    description: "对供应商进行多维度数据分析，生成可视化图表报告",
    prompt: "帮我对所有供应商进行综合分析，生成对比图表",
  },
  {
    icon: "🛒",
    title: "采购下单",
    description: "智能创建采购订单，支持数据补充和审批流程",
    prompt: "帮我新增一个采购订单",
  },
  {
    icon: "📦",
    title: "库存预警",
    description: "实时监控库存水位，及时发现低库存零部件",
    prompt: "查看当前库存预警信息",
  },
  {
    icon: "🔍",
    title: "零部件查询",
    description: "快速检索零部件信息、价格及供应商关联",
    prompt: "查询所有零部件的库存和价格信息",
  },
];

interface Props {
  onPromptClick: (prompt: string) => void;
}

export default function WelcomeScreen({ onPromptClick }: Props) {
  return (
    <div className="flex-1 overflow-y-auto px-8 py-10">
      <div className="mx-auto max-w-5xl w-full text-center">
        {/* 标题 */}
        <h1 className="text-2xl font-bold text-gray-900 mb-2">
          基于 Harness Engineering 的智能助手
        </h1>
        <p className="text-sm text-gray-500 mb-8">
          DeepAgent 智能采购助手 — 集成供应商分析、订单管理、库存监控于一体
        </p>

        {/* 功能卡片 2x2 */}
        <div className="mx-auto grid max-w-2xl grid-cols-1 gap-4 sm:grid-cols-2">
          {CARDS.map((card) => (
            <CapabilityCardComponent
              key={card.title}
              card={card}
              onClick={onPromptClick}
            />
          ))}
        </div>
        <QuickAccess onPromptClick={onPromptClick} />
      </div>
    </div>
  );
}
