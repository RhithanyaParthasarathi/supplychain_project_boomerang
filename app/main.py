# app/main.py
from fastapi import FastAPI, Depends, HTTPException, status
from pymongo.collection import Collection
from datetime import datetime, timedelta
import uuid
import asyncio
import httpx # Use the async client in your API endpoints
import requests # Use the sync client in the threaded consumer
from functools import partial

from app.models import ReturnRequest, InspectionRequest
from app.database import get_returns_collection, get_orders_collection
from app.kafka_utils import create_kafka_producer, create_kafka_consumer
from app.config import (
    KAFKA_TOPIC_RETURN_REQUESTS,
    KAFKA_TOPIC_ITEMS_RECEIVED,
    KAFKA_TOPIC_ITEMS_INSPECTED,
    KAFKA_TOPIC_CASES_CLOSED
)
from kafka import KafkaProducer

app = FastAPI(title="Project Boomerang - GadgetGrove Returns (Event-Driven)")

# === KAFKA CONSUMER LOGIC (Corrected Version) ===

def blocking_consumer_task(consumer, topic, endpoint):
    """
    This function contains the blocking consumer loop.
    It will be run in a separate thread.
    """
    print(f"INFO: Consumer for topic '{topic}' started on a background thread.")
    for message in consumer:
        try:
            message_data = message.value
            rma_id = message_data.get("RMA_id")
            print(f"CONSUMER ({topic}): Received event for RMA '{rma_id}'")
            
            full_endpoint = f"http://localhost:8000{endpoint.format(rma_id=rma_id)}"
            
            # Since this runs in a sync thread, we use the 'requests' library
            response = requests.post(full_endpoint)
            response.raise_for_status() # Raise an exception for 4xx/5xx responses
            print(f"CONSUMER ({topic}): Successfully processed RMA '{rma_id}'")

        except Exception as e:
            print(f"ERROR: Consumer for topic {topic} failed: {e}")

async def run_consumer_in_background(topic, endpoint):
    """
    This async function gets the event loop and runs the blocking
    consumer task in a thread pool executor.
    """
    loop = asyncio.get_running_loop()
    consumer = create_kafka_consumer(topic)
    # The 'partial' function is used to pass arguments to the target function
    # when running it in the executor.
    await loop.run_in_executor(None, partial(blocking_consumer_task, consumer, topic, endpoint))


@app.on_event("startup")
async def startup_event():
    print("INFO: Launching Kafka consumers in background threads...")
    asyncio.create_task(run_consumer_in_background(KAFKA_TOPIC_RETURN_REQUESTS, "/returns/{rma_id}/receive"))
    asyncio.create_task(run_consumer_in_background(KAFKA_TOPIC_ITEMS_RECEIVED, "/returns/{rma_id}/inspect"))
    asyncio.create_task(run_consumer_in_background(KAFKA_TOPIC_ITEMS_INSPECTED, "/returns/{rma_id}/close"))
    print("INFO: Consumers are being set up.")
    # The startup event can now complete without waiting for the consumers.


# === API ENDPOINTS (Mostly unchanged, still use async httpx if needed internally) ===

@app.post("/returns/request", status_code=status.HTTP_201_CREATED)
async def request_return(
    return_request: ReturnRequest,
    returns_collection: Collection = Depends(get_returns_collection),
    orders_collection: Collection = Depends(get_orders_collection),
    kafka_producer: KafkaProducer = Depends(create_kafka_producer)
):
    order = await orders_collection.find_one({"_id": return_request.order_id})
    if not order:
        raise HTTPException(status_code=404, detail=f"Order '{return_request.order_id}' not found.")
    
    if "purchase_date" not in order or datetime.utcnow() > (order.get("purchase_date") + timedelta(days=30)):
        raise HTTPException(status_code=400, detail="Return window is closed.")

    unique_id = str(uuid.uuid4().hex)[:6].upper()
    timestamp = datetime.utcnow().strftime('%Y%m%d')
    rma_id = f"RMA-{timestamp}-{unique_id}"
    
    rma_document_data = {
        "_id": rma_id, "order_id": return_request.order_id, "item_id": return_request.item_id,
        "status": "AWAITING_RETURN", "reason_for_return": return_request.reason_for_return,
        "shipping_label_url": f"/labels/{rma_id}.pdf", "return_request_date": datetime.utcnow(),
        "last_updated": datetime.utcnow()
    }
    await returns_collection.insert_one(rma_document_data)

    event_data = {"RMA_id": rma_id}
    kafka_producer.send(KAFKA_TOPIC_RETURN_REQUESTS, value=event_data)
    kafka_producer.flush()
    print(f"PRODUCER: Sent event to '{KAFKA_TOPIC_RETURN_REQUESTS}' for new RMA '{rma_id}'")
    
    return {"RMA_id": rma_id, "status": "AWAITING_RETURN"}

@app.post("/returns/{rma_id}/receive", status_code=status.HTTP_200_OK)
async def receive_item(
    rma_id: str,
    returns_collection: Collection = Depends(get_returns_collection),
    kafka_producer: KafkaProducer = Depends(create_kafka_producer)
):
    result = await returns_collection.find_one_and_update(
        {"_id": rma_id, "status": "AWAITING_RETURN"},
        {"$set": {"status": "RECEIVED", "arrival_date": datetime.utcnow(), "last_updated": datetime.utcnow()}}
    )
    if not result:
        raise HTTPException(status_code=404, detail=f"RMA '{rma_id}' not found or not in AWAITING_RETURN state.")

    event_data = {"RMA_id": rma_id}
    kafka_producer.send(KAFKA_TOPIC_ITEMS_RECEIVED, value=event_data)
    kafka_producer.flush()
    print(f"PRODUCER: Sent event to '{KAFKA_TOPIC_ITEMS_RECEIVED}' for received RMA '{rma_id}'")
    
    return {"RMA_id": rma_id, "status": "RECEIVED"}
# === STAGE 3: Inspection Completed (NEW UNIVERSAL VERSION) ===
'''@app.post("/returns/{rma_id}/inspect", status_code=status.HTTP_200_OK)
async def inspect_item(
    rma_id: str,
    # This is the key change: Make the request body optional.
    inspection_request: InspectionRequest | None = None,
    returns_collection: Collection = Depends(get_returns_collection),
    kafka_producer: KafkaProducer = Depends(create_kafka_producer)
):
    """
    (Called by a Kafka consumer OR manually via an API tool like Swagger)
    Logs the inspection result against the RMA and updates the status.
    If called without a request body, it defaults the result to 'RESELLABLE'.
    If called with a request body, it uses the provided result.
    """
    # --- Logic to determine the inspection result ---
    result_to_save = ""
    if inspection_request:
        # PATH 1: MANUAL TRIGGER (e.g., Swagger)
        # If a body was provided, use the value from it.
        result_to_save = inspection_request.inspection_result.value
        print(f"INFO: Manual inspection for RMA '{rma_id}'. Result received: {result_to_save}")
    else:
        # PATH 2: AUTOMATED TRIGGER (e.g., Kafka Consumer)
        # If no body was provided, use the default value.
        result_to_save = 'RESELLABLE'
        print(f"INFO: Automated inspection for RMA '{rma_id}'. Defaulting to {result_to_save}")

    # --- Common logic for both paths ---

    # Find the document and update it with the determined result
    result = await returns_collection.find_one_and_update(
        {"_id": rma_id, "status": "RECEIVED"},
        {"$set": {
            "status": "INSPECTION_COMPLETE",
            "inspection_result": result_to_save, # Use the determined result here
            "inspection_date": datetime.utcnow(),
            "last_updated": datetime.utcnow()
        }}
    )

    # State validation
    if not result:
        raise HTTPException(status_code=404, detail=f"RMA '{rma_id}' not found or not in RECEIVED state.")

    # Produce the next Kafka event with the actual result that was saved
    event_data = {"RMA_id": rma_id, "inspection_result": result_to_save}
    kafka_producer.send(KAFKA_TOPIC_ITEMS_INSPECTED, value=event_data)
    kafka_producer.flush()
    print(f"PRODUCER: Sent event to '{KAFKA_TOPIC_ITEMS_INSPECTED}' for inspected RMA '{rma_id}'")

    # Return the actual result in the API response
    return {"RMA_id": rma_id, "status": "INSPECTION_COMPLETE", "inspection_result": result_to_save}'''

@app.post("/returns/{rma_id}/inspect", status_code=status.HTTP_200_OK)
async def inspect_item(
    rma_id: str,
    # Make the request body Optional.
    inspection_request: InspectionRequest | None = None,
    returns_collection: Collection = Depends(get_returns_collection),
    kafka_producer: KafkaProducer = Depends(create_kafka_producer)
):
    """
    (Called by a Kafka consumer OR manually)
    Updates status to INSPECTION_COMPLETE and produces the next event.
    """
    # Determine the inspection result
    if inspection_request:
        # If a body was provided (e.g., from Swagger), use that value.
        result_value = inspection_request.inspection_result.value
        print(f"INFO: Manual inspection for RMA '{rma_id}'. Result: {result_value}")
    else:
        # If no body was provided (e.g., from the consumer), use the default.
        result_value = 'RESELLABLE'
        print(f"INFO: Automated inspection for RMA '{rma_id}'. Defaulting to {result_value}")

    result = await returns_collection.find_one_and_update(
        {"_id": rma_id, "status": "RECEIVED"},
        {"$set": {
            "status": "INSPECTION_COMPLETE",
            "inspection_result": result_value,
            "inspection_date": datetime.utcnow(),
            "last_updated": datetime.utcnow()
        }}
    )
    if not result:
        raise HTTPException(status_code=404, detail=f"RMA '{rma_id}' not found or not in RECEIVED state.")

    event_data = {"RMA_id": rma_id, "inspection_result": result_value}
    kafka_producer.send(KAFKA_TOPIC_ITEMS_INSPECTED, value=event_data)
    kafka_producer.flush()
    print(f"PRODUCER: Sent event to '{KAFKA_TOPIC_ITEMS_INSPECTED}' for inspected RMA '{rma_id}'")

    return {"RMA_id": rma_id, "status": "INSPECTION_COMPLETE", "inspection_result": result_value}

@app.post("/returns/{rma_id}/close", status_code=status.HTTP_200_OK)
async def close_case(
    rma_id: str, returns_collection: Collection = Depends(get_returns_collection),
    kafka_producer: KafkaProducer = Depends(create_kafka_producer)
):
    # First check if the RMA exists at all
    rma = await returns_collection.find_one({"_id": rma_id})
    if not rma:
        raise HTTPException(status_code=404, detail=f"RMA '{rma_id}' not found.")
    
    # Then check if it's in the correct state
    if rma.get("status") != "INSPECTION_COMPLETE":
        raise HTTPException(
            status_code=400, 
            detail=f"RMA '{rma_id}' is in status '{rma.get('status')}' but must be in 'INSPECTION_COMPLETE' state to be closed."
        )
    
    if rma.get("inspection_result") == "RESELLABLE":
        print(f"INFO: Initiating FULL refund for order {rma.get('order_id')}...")

    await returns_collection.update_one(
        {"_id": rma_id},
        {"$set": {"status": "CLOSED", "refund_processed_date": datetime.utcnow(), "last_updated": datetime.utcnow()}}
    )
    
    event_data = {"RMA_id": rma_id, "status": "CLOSED"}
    kafka_producer.send(KAFKA_TOPIC_CASES_CLOSED, value=event_data)
    kafka_producer.flush()
    print(f"FINAL STAGE: RMA '{rma_id}' has been closed. Event sent to '{KAFKA_TOPIC_CASES_CLOSED}'")
    return {"RMA_id": rma_id, "status": "CLOSED"}


'''# app/main.py without kafka
from fastapi import FastAPI, Depends, HTTPException, status
from pymongo.collection import Collection
from datetime import datetime, timedelta
import uuid

# Import the new models
from app.models import ReturnRequest, RMADocument, InspectionRequest
from app.database import get_returns_collection, get_orders_collection

app = FastAPI(title="Project Boomerang - GadgetGrove Returns")


# === STAGE 1: Return Authorization Requested ===

# === STAGE 1: Return Authorization Requested (NOW WITH VALIDATION) ===
@app.post("/returns/request", status_code=status.HTTP_201_CREATED)
async def request_return(
    return_request: ReturnRequest,
    returns_collection: Collection = Depends(get_returns_collection),
    # Add a dependency for the orders collection
    orders_collection: Collection = Depends(get_orders_collection)
):
    """
    Validates a customer's return request and, if valid, generates a
    unique Return Merchandise Authorization (RMA) and a shipping label.
    """
    # --- NEW VALIDATION LOGIC ---
    # Step 1: Find the original order in the 'orders' collection.
    order = await orders_collection.find_one({"_id": return_request.order_id})
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order with ID '{return_request.order_id}' not found."
        )

    # Step 2: Check if the return is within the 30-day window.
    purchase_date = order.get("purchase_date")
    if not purchase_date:
        # Failsafe in case the order data is malformed
        raise HTTPException(status_code=500, detail="Order purchase date not found.")

    return_deadline = purchase_date + timedelta(days=30)
    
    if datetime.utcnow() > return_deadline:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Return window closed. Order was placed on {purchase_date.strftime('%Y-%m-%d')}."
        )
    # --- END OF VALIDATION LOGIC ---


    # This part only runs if the validation passes
    unique_id = str(uuid.uuid4().hex)[:6].upper()
    timestamp = datetime.utcnow().strftime('%Y%m%d')
    rma_id = f"RMA-{timestamp}-{unique_id}"
    shipping_label_url = f"/labels/{rma_id}.pdf"

    rma_document = RMADocument(
        RMA_id=rma_id,
        order_id=return_request.order_id,
        item_id=return_request.item_id,
        status="AWAITING_RETURN",
        reason_for_return=return_request.reason_for_return,
        shipping_label_url=shipping_label_url,
    ).model_dump(by_alias=True)

    await returns_collection.insert_one(rma_document)

    return {
        "RMA_id": rma_id,
        "status": "AWAITING_RETURN",
        "shipping_label_url": shipping_label_url,
        "message": "Return request authorized. Please use the provided shipping label."
    }

# NEW CODE STARTS HERE #

# === STAGE 2: Item Received at Warehouse ===
@app.post("/returns/{rma_id}/receive", status_code=status.HTTP_200_OK)
async def receive_item(
    rma_id: str,
    returns_collection: Collection = Depends(get_returns_collection)
):
    """
    Updates the RMA status to 'RECEIVED' when the item arrives at the warehouse.
    This is triggered by a warehouse worker scanning the return label.
    """
    # Find the RMA document. If not found, raise a 404 error.
    rma = await returns_collection.find_one({"_id": rma_id})
    if not rma:
        raise HTTPException(status_code=404, detail=f"RMA with ID '{rma_id}' not found.")

    # State validation: Ensure the RMA is in the correct state to be received.
    if rma.get("status") != "AWAITING_RETURN":
        raise HTTPException(status_code=400, detail=f"RMA '{rma_id}' is in status '{rma.get('status')}' and cannot be received.")

    # Update the document in MongoDB
    await returns_collection.update_one(
        {"_id": rma_id},
        {
            "$set": {
                "status": "RECEIVED",
                "arrival_date": datetime.utcnow(),
                "last_updated": datetime.utcnow()
            }
        }
    )

    return {"RMA_id": rma_id, "status": "RECEIVED", "message": "Item successfully marked as received."}


# === STAGE 3: Inspection Completed ===
@app.post("/returns/{rma_id}/inspect", status_code=status.HTTP_200_OK)
async def inspect_item(
    rma_id: str,
    inspection_request: InspectionRequest,
    returns_collection: Collection = Depends(get_returns_collection)
):
    """
    Logs the inspection result against the RMA and updates the status.
    Triggered by a technician submitting their findings.
    """
    rma = await returns_collection.find_one({"_id": rma_id})
    if not rma:
        raise HTTPException(status_code=404, detail=f"RMA with ID '{rma_id}' not found.")
        
    if rma.get("status") != "RECEIVED":
        raise HTTPException(status_code=400, detail=f"RMA '{rma_id}' is in status '{rma.get('status')}' and cannot be inspected.")

    await returns_collection.update_one(
        {"_id": rma_id},
        {
            "$set": {
                "status": "INSPECTION_COMPLETE",
                "inspection_result": inspection_request.inspection_result.value,
                "inspection_date": datetime.utcnow(),
                "last_updated": datetime.utcnow()
            }
        }
    )
    
    return {"RMA_id": rma_id, "status": "INSPECTION_COMPLETE", "inspection_result": inspection_request.inspection_result.value}


# === STAGE 4: Refund Processed & Case Closed ===
@app.post("/returns/{rma_id}/close", status_code=status.HTTP_200_OK)
async def close_case(
    rma_id: str,
    returns_collection: Collection = Depends(get_returns_collection)
):
    """
    Based on inspection, triggers a refund (simulated) and closes the RMA case.
    """
    rma = await returns_collection.find_one({"_id": rma_id})
    if not rma:
        raise HTTPException(status_code=404, detail=f"RMA with ID '{rma_id}' not found.")

    if rma.get("status") != "INSPECTION_COMPLETE":
        raise HTTPException(status_code=400, detail=f"RMA '{rma_id}' is in status '{rma.get('status')}' and cannot be closed.")

    # --- Business Logic for Closing ---
    message = f"RMA '{rma_id}' has been closed."
    inspection_result = rma.get("inspection_result")
    
    if inspection_result == "RESELLABLE":
        # Simulate calling a finance API to process a full refund.
        print(f"INFO: Initiating FULL refund for order {rma.get('order_id')}...")
        message = f"A full refund has been processed and RMA '{rma_id}' is now closed."
        # You would call your finance API here.
    
    elif inspection_result in ["DAMAGED", "MISSING_PARTS"]:
        # Simulate escalating to customer service or issuing a partial refund.
        print(f"INFO: Escalating case for RMA '{rma_id}' due to condition: {inspection_result}")
        message = f"RMA '{rma_id}' requires manual review and is now closed pending action."
        # You might have a different status here, like "PENDING_REVIEW".

    # Update the document to its final state
    await returns_collection.update_one(
        {"_id": rma_id},
        {
            "$set": {
                "status": "CLOSED",
                "refund_processed_date": datetime.utcnow(), # Or only set if refund was full
                "last_updated": datetime.utcnow()
            }
        }
    )

    return {"RMA_id": rma_id, "status": "CLOSED", "message": message}'''