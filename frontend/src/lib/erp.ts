export interface PageResult<T> {
  records: T[];
  total: number;
  pages: number;
  current: number;
  size: number;
}

export interface PartSummary {
  id: number;
  partCode?: string;
  name?: string;
  model?: string;
  unit?: string;
}

export interface SupplierOption {
  id: number;
  partId: number;
  supplierId: number;
  supplierCode?: string;
  supplierName?: string;
  supplierStatus?: number;
  supplierPartCode?: string;
  purchasePrice: number;
  minimumOrderQuantity: number;
  leadTimeDays?: number;
  qualityRating?: number;
  lastPurchaseTime?: string;
  enabled: boolean;
  defaultSupplier: boolean;
}

export interface VehicleModel {
  id: number;
  brand: string;
  series?: string;
  model: string;
  modelYearStart?: number;
  modelYearEnd?: number;
  displacement?: number;
  engineCode?: string;
  remark?: string;
}

export interface PartFitment {
  id: number;
  partId: number;
  vehicleModelId: number;
  fitmentNote?: string;
  verified: boolean;
  createTime?: string;
  vehicleModel: VehicleModel;
}

export interface PurchaseOrderLine {
  id?: number;
  partId: number;
  quantity: number;
  unitPrice: number;
  subtotal?: number;
  remark?: string;
  partDetail?: PartSummary;
}

export interface PurchaseOrder {
  id: number;
  orderNumber: string;
  supplierId?: number;
  totalAmount?: number;
  status: number;
  orderTime?: string;
  expectedDeliveryDate?: string;
  actualDeliveryDate?: string;
  remark?: string;
  orderDetail?: PurchaseOrderLine[];
}

export interface ReplenishmentTask {
  id: number;
  taskNo: string;
  partId: number;
  currentQuantity: number;
  safetyStock: number;
  suggestedQuantity: number;
  preferredSupplierId?: number;
  reason?: string;
  status: "PENDING" | "ORDER_CREATED" | "COMPLETED" | "CANCELLED";
  source: "MANUAL" | "AUTO_INSPECTION";
  relatedOrderId?: number;
  inspectionDate?: string;
  createTime?: string;
}

export interface InventoryTransaction {
  id: number;
  transactionNo: string;
  partId: number;
  transactionType: string;
  quantity: number;
  beforeQuantity: number;
  afterQuantity: number;
  sourceType?: string;
  sourceId?: number;
  operationId?: string;
  operatorId?: number;
  warehouseLocation?: string;
  remark?: string;
  occurredAt?: string;
}

export interface PurchaseReturn {
  id: number;
  returnNumber: string;
  purchaseOrderId: number;
  partId: number;
  quantity: number;
  reasonType: string;
  reason?: string;
  status: "PENDING" | "CONFIRMED";
  operationId?: string;
  confirmOperationId?: string;
  createdBy?: number;
  confirmedBy?: number;
  confirmedAt?: string;
  createTime?: string;
}

export const ORDER_STATUS: Record<number, string> = {
  1: "待审核",
  2: "已审核",
  3: "采购中",
  4: "已入库",
  5: "已取消",
};

export const TRANSACTION_TYPE: Record<string, string> = {
  PURCHASE_RECEIPT: "采购入库",
  MANUAL_INBOUND: "手工入库",
  MANUAL_OUTBOUND: "手工出库",
  PURCHASE_RETURN: "采购退货",
  STOCK_ADJUSTMENT: "库存调整",
};

export const RETURN_REASON: Record<string, string> = {
  QUANTITY_MISMATCH: "数量不符",
  DAMAGED: "零件损坏",
  SPEC_MISMATCH: "规格不符",
  QUALITY_ISSUE: "质量问题",
  OTHER: "其他",
};

export function buildQuery(values: Record<string, string | number | null | undefined>): string {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined && value !== null && String(value).trim() !== "") {
      params.set(key, String(value));
    }
  });
  const query = params.toString();
  return query ? `?${query}` : "";
}

export function newOperationId(scope: string): string {
  return `${scope}-${crypto.randomUUID()}`;
}

export function operationHeaders(operationId: string): HeadersInit {
  return { "X-Operation-Id": operationId, "Idempotency-Key": operationId };
}

export function money(value?: number): string {
  if (value === undefined || value === null || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("zh-CN", { style: "currency", currency: "CNY" }).format(value);
}
