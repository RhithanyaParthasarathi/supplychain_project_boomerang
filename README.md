# Project Boomerang - GadgetGrove Returns Automation

**Project Boomerang** is the backend platform for GadgetGrove, a fictional e-commerce retailer. It is designed to fully automate the customer electronics return lifecycle, from the initial return request to the final case closure.

This system is built as an event-driven, asynchronous application using Python, FastAPI, MongoDB, and Apache Kafka. It adheres to modern microservice principles like stateful awareness, unique identification for traceability, and maintaining a consistent "Digital Thread" for every return.

## Core Features & Workflow

The platform automates the four main stages of the customer return process:

1.  **Stage 1: Return Authorization Requested**
    *   An external system calls the `POST /returns/request` endpoint.
    *   The system validates that the original order is within the 30-day return window.
    *   If valid, it generates a unique **Return Merchandise Authorization ID (RMA_id)** and sets the status to `AWAITING_RETURN`.
    *   A Kafka event is produced to kickstart the internal warehouse workflow.

2.  **Stage 2: Item Received at Warehouse**
    *   A Kafka consumer listens for new return requests and automatically calls the `POST /returns/{rma_id}/receive` endpoint.
    *   The RMA's status is updated to `RECEIVED`, and the arrival date is logged.
    *   A new Kafka event is produced to signal the item is ready for inspection.

3.  **Stage 3: Inspection Completed**
    *   A Kafka consumer listens for received items and calls the `POST /returns/{rma_id}/inspect` endpoint.
    *   The inspection result is logged, and the status is updated to `INSPECTION_COMPLETE`.
    *   A final Kafka event is produced to trigger case closure.

4.  **Stage 4: Refund Processed & Case Closed**
    *   A Kafka consumer listens for completed inspections and calls the `POST /returns/{rma_id}/close` endpoint.
    *   Based on the inspection result, the system takes the appropriate action (e.g., simulates a refund or an escalation).
    *   The RMA's final status is updated to `CLOSED`, completing the lifecycle.

## Technical Architecture & Design

### Technologies Used
*   **Backend Framework:** FastAPI (Python 3)
*   **Database:** MongoDB
*   **Message Broker:** Apache Kafka
*   **Containerization:** Docker & Docker Compose
*   **Key Python Libraries:** `uvicorn`, `motor`, `kafka-python`, `httpx`, `requests`

### Core Principles
*   **The Digital Thread:** A single, evolving document in a MongoDB `returns` collection serves as the source of truth for every return.
*   **Traceability:** Every return is tracked by a unique, generated `RMA_id`.
*   **Real-Time Stateful Awareness:** The system is built as a state machine, with API logic preventing invalid state transitions.
*   **Event-Driven Orchestration:** Stages are chained together asynchronously using Kafka topics.

## Assumptions and Design Decisions

To meet the project goals and focus on the core backend logic, the following assumptions and design decisions have been made:

1.  **Assumption: Existing Orders Data for 30-Day Window Validation:** The system assumes that an `orders` collection already exists in the database, containing purchase details like `_id` and `purchase_date`. The application **reads from** this collection to validate the 30-day return policy but is not responsible for creating the orders themselves. This simulates a real-world scenario where the Returns service is separate from the Order Management service.

2.  **Assumption: Default "RESELLABLE" State for Automation:** For the end-to-end automated workflow demonstration, the inspection stage, when triggered by a Kafka consumer, defaults to a result of **"RESELLABLE"**. This is a deliberate choice to allow the Kafka-driven chain to run from start to finish without requiring manual human input, effectively demonstrating the "happy path."

3.  **Design Decision: Use of `POST` for All State-Changing Endpoints:** All endpoints that cause a change in the state of a return (`/receive`, `/inspect`, `/close`) use the `POST` HTTP method. This is a pragmatic design choice that treats each step as a "command" or an "action" being sent to the system. It provides a simple and consistent API for a workflow-oriented service, prioritizing clarity over strict REST formalism where `PATCH` or `PUT` might also be considered.

4.  **Simulated API Calls:** External API calls (e.g., to a Finance API for refunds) are simulated with `print()` statements.

5.  **Manual Testing of Other Scenarios:** The `inspect` endpoint is designed to be universal. While the automated flow defaults to "RESELLABLE," the endpoint can be called manually (e.g., via the Swagger UI) with a request body specifying **"DAMAGED"** or **"MISSING_PARTS"** to test and verify the system's logic for handling these exception cases.

## How to Set Up and Run the Project

### Prerequisites
*   Docker Desktop installed and running.
*   Python 3.10+ installed.
*   A running MongoDB instance.

### Step-by-Step Instructions
1.  **Clone the Repository:**
    ```bash
    git clone <your-repo-url>
    cd gadgetgrove_project
    ```
2.  **Set up Python Environment:**
    ```bash
    python -m venv venv
    # On Windows PowerShell:
    .\venv\Scripts\Activate.ps1
    # Install dependencies from requirements.txt
    pip install -r requirements.txt 
    # (Note: You should create a requirements.txt file via `pip freeze > requirements.txt`)
    ```
3.  **Start Infrastructure (Kafka & Zookeeper):**
    ```bash
    docker-compose up -d
    ```
4.  **Start the MongoDB Server:**
    *   Ensure your MongoDB server is running. If installed manually on Windows, you may need to run this in a separate terminal:
    ```powershell
    >> "C:\Program Files\MongoDB\Server\8.2\bin\mongod.exe"
    ```
5.  **Prepare Sample Data:**
    *   Using MongoDB Compass, connect to your database.
    *   In the `gadgetgrove` database, create an `orders` collection.
    *   Insert a sample order document to test against, ensuring the `purchase_date` is recent. Example:
    ```json
    { "_id": "ORD-5544", "purchase_date": { "$date": "2025-10-01T10:00:00.000Z" } }
    ```
6.  **Run the FastAPI Application:**
    ```bash
    uvicorn app.main:app --reload
    ```
    *   The server will be running at `http://127.0.0.1:8000`.

## How to Test the Workflow
1.  **Access the API Documentation:** Open your browser to `http://127.0.0.1:8000/docs`.
2.  **Trigger the Workflow:**
    *   Use the `POST /returns/request` endpoint to create a new return for a valid order ID (e.g., `"ORD-5544"`).
    ```json
    { "order_id": "ORD-5544", "item_id": "GADGET-X1", "reason_for_return": "damaged product was given" }
    ```
3.  **Observe the Automation:**
    *   Check the terminal where the Uvicorn server is running. You will see a sequence of log messages from the Kafka producers and consumers as the RMA automatically progresses through each stage.
4.  **Verify the Final State:**
    *   In MongoDB Compass, check the `returns` collection. The document for the RMA you created will have a final status of `CLOSED`.
