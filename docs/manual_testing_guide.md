# Manual Testing Guide — Architecture Improvements

This guide details how to verify the new query capabilities, dimension support, dynamic SQL compilation, and intent garbage filtering.
---

## Understanding the Reviewer Feedback & Solutions

Here is what the reviewer's feedback meant, why the original system failed, and how the new design solves it:

### Problem 1: Limited Query Flexibility
* **What the feedback meant**: The system was originally hardcoded to look only for a single metric over a rolling time window (e.g. `SUM(purchase_amount) >= boundary`). Real-world business queries need lists, rankings, and filters (e.g. *"Show all purchases made by Sandeep"* or *"top 10 customers"*).
* **The Solution**: We evolved the layer contract from passing simple flat strings to a **Structured Query Schema** that handles projection, filtering (using dynamic operators), ordering, and limits.

### Problem 2: Dimensions Are Not Fully Utilized
* **What the feedback meant**: The system had columns like `product` and `customer_name` in config, but couldn't use them to segment metrics (e.g., breakdown sales *by* product).
* **The Solution**: We integrated dimensions as first-class keys. Queries like `"revenue by product"` now dynamically group the metric `total_sales` by the dimension `product` in the SQL compilation step.

### Problem 3: Limited SQL Generation Capability
* **What the feedback meant**: The previous data layer could only generate one SQL template: `SELECT SUM(col) FROM tbl WHERE date >= boundary`. It couldn't generate `GROUP BY`, `ORDER BY`, `LIMIT`, or filter comparisons like `col > 20000`.
* **The Solution**: We re-wrote the Data Layer to read the schema mappings and dynamically compile SQLAlchemy select statements containing `group_by`, `order_by`, `limit`, and relational comparison filters.

### Problem 4: Weak Intent Detection
* **What the feedback meant**: The system used simple word-matching anywhere in the text. For example, a random string containing garbage like `"sdfsdfsdfsdf sales dsfsdfsdfsdfsdfs this week"` was recognized as a valid sales query because it contained the keywords `sales` and `this week`.
* **The Solution**: We added a **Garbage filter** in the Intent Layer. It tokenizes the input text and rejects the query if more than 30% of the non-stop words are garbage/random terms (using length and vowel-ratio heuristics).

---

## 1. Local Server Setup

Make sure your database is seeded and the backend server is running:

1. **Seed the database** (clears old data and sets up deterministically dated customer records):
   ```bash
   python -m backend.seed
   ```
2. **Start the FastAPI backend**:
   ```bash
   uvicorn backend.main:app --reload --port 8080
   ```

---

## 2. Test Scenarios & Commands

You can test these using `curl` directly from your terminal or any API client (e.g. Postman).

### Scenario A: Stricter Intent Filtering (Problem 4)
* **Goal**: Prove that random keyboard-mash input containing valid keywords is rejected, rather than processed as a valid query.
* **Test Command**:
  ```bash
  curl -X POST http://127.0.0.1:8080/ask \
    -H "Content-Type: application/json" \
    -d '{"text": "sdfsdfsdfsdf sales dsfsdfsdfsdfsdfs this week"}'
  ```
* **Expected Output**:
  - The request should return successfully (`status: 200`), but contain an error envelope indicating `INTENT_NOT_FOUND`:
  ```json
  {
    "status": "error",
    "error": {
      "code": "INTENT_NOT_FOUND",
      "message": "Query contains too many unrecognized or garbage terms."
    }
  }
  ```

---

### Scenario B: Ranking & Top-N Queries (Problem 1 & 3)
* **Goal**: Request a sorted breakdown of the top customers.
* **Test Command**:
  ```bash
  curl -X POST http://127.0.0.1:8080/ask \
    -H "Content-Type: application/json" \
    -d '{"text": "Who are the top 3 customers by purchase amount?"}'
  ```
* **Expected Output**:
  - The pipeline compiles the query using `GROUP BY customer_name ORDER BY total_sales DESC LIMIT 3` and formats the results in a list:
  ```json
  {
    "status": "ok",
    "payload": {
      "text": "1. Vijay Rao: ₹30,000\n2. Meena Iyer: ₹25,000\n3. Asha Verma: ₹20,000",
      "value": [
        {"customer_name": "Vijay Rao", "total_sales": 30000},
        {"customer_name": "Meena Iyer", "total_sales": 25000},
        {"customer_name": "Asha Verma", "total_sales": 20000}
      ]
    }
  }
  ```

---

### Scenario C: Highest Revenue & Date Breakdown (Problem 1, 2, & 3)
* **Goal**: Retrieve the date with the highest sales and product breakdown.
* **Test Command (Highest Sales Day)**:
  ```bash
  curl -X POST http://127.0.0.1:8080/ask \
    -H "Content-Type: application/json" \
    -d '{"text": "Which day had the highest sales?"}'
  ```
* **Expected Output**:
  - Should return the date and formatted revenue value (e.g. `2026-06-12 generated ₹30,000`).

---

### Scenario D: Detailed Purchase Record Retrieval (Problem 1 & 2)
* **Goal**: Retrieve specific raw record columns filtered dynamically by customer name.
* **Test Command**:
  ```bash
  curl -X POST http://127.0.0.1:8080/ask \
    -H "Content-Type: application/json" \
    -d '{"text": "Show all purchases made by Asha Verma"}'
  ```
* **Expected Output**:
  - Matches the `customer_name = 'Asha Verma'` filter and lists individual record details:
  ```json
  {
    "status": "ok",
    "payload": {
      "text": "Customer name: Asha Verma, Product: Widget, Purchase date: 2026-06-27, Purchase amount: ₹20,000"
    }
  }
  ```

---

### Scenario E: High-Value Filters (Problem 1 & 3)
* **Goal**: Find customers whose purchase amounts exceed a dynamic numeric value threshold.
* **Test Command**:
  ```bash
  curl -X POST http://127.0.0.1:8080/ask \
    -H "Content-Type: application/json" \
    -d '{"text": "Which customers made purchases above 20000?"}'
  ```
* **Expected Output**:
  - Returns a list containing `Vijay Rao` and `Meena Iyer` (since Asha Verma is exactly 20000 and the query checks strictly greater than).
