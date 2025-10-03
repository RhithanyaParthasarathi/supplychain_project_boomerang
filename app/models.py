# app/models.py
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum

# Using an Enum to restrict the possible values for inspection results
class InspectionResultEnum(str, Enum):
    resellable = "RESELLABLE"
    damaged = "DAMAGED"
    missing_parts = "MISSING_PARTS"


# === REQUEST MODELS (What the user sends to us) ===

# Model for Stage 1: Customer requests a return
class ReturnRequest(BaseModel):
    order_id: str
    item_id: str
    reason_for_return: Optional[str] = None

# Model for Stage 3: Technician submits inspection findings
class InspectionRequest(BaseModel):
    inspection_result: InspectionResultEnum


# === DATABASE MODEL (How the data is stored in MongoDB) ===

class RMADocument(BaseModel):
    RMA_id: str = Field(alias="_id") # Using RMA_id as the primary key _id
    order_id: str
    item_id: str
    status: str
    reason_for_return: Optional[str] = None
    shipping_label_url: str
    return_request_date: datetime = Field(default_factory=datetime.utcnow)
    
    # These fields will be added in later stages
    arrival_date: Optional[datetime] = None
    inspection_result: Optional[InspectionResultEnum] = None
    inspection_date: Optional[datetime] = None
    refund_processed_date: Optional[datetime] = None
    
    last_updated: datetime = Field(default_factory=datetime.utcnow)

    model_config = {
        "populate_by_name": True,  # Allows using alias '_id' with field name 'RMA_id'
        "json_schema_extra": {
            "example": {
                "_id": "RMA-20251003-12345",
                "order_id": "ORD-5544",
                "item_id": "GADGET-X1",
                "status": "CLOSED",
                "reason_for_return": "Item was defective.",
                "shipping_label_url": "/labels/RMA-20251003-12345.pdf",
                "return_request_date": "2025-10-03T10:00:00Z",
                "arrival_date": "2025-10-05T09:00:00Z",
                "inspection_result": "RESELLABLE",
                "inspection_date": "2025-10-05T11:30:00Z",
                "refund_processed_date": "2025-10-05T12:00:00Z",
                "last_updated": "2025-10-05T12:00:00Z"
            }
        }
    }