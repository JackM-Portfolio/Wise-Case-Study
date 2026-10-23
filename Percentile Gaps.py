import sqlite3
import pandas as pd

conn = sqlite3.connect("clean_data.db")

query = """
WITH daily AS (
    SELECT customer_id, DATE(Transaction_date) AS txn_date
    FROM my_table
    GROUP BY 1, 2
),
gaps AS (
    SELECT julianday(txn_date)
           - julianday(LAG(txn_date) OVER (PARTITION BY customer_id ORDER BY txn_date)) AS gap
    FROM daily
),
ranked AS (
    SELECT gap,
           ROW_NUMBER() OVER (ORDER BY gap) AS rn,
           COUNT(*)     OVER ()             AS n
    FROM gaps
    WHERE gap IS NOT NULL
),
pcts(p) AS (
    VALUES (0.5), (0.75), (0.9), (0.95), (0.99)
)
SELECT p AS percentile,
       (SELECT gap
        FROM ranked
        WHERE rn = MAX(1, CAST(ROUND(p * n + 0.4999999) AS INTEGER))
        LIMIT 1) AS gap_days
FROM pcts;
"""

df = pd.read_sql_query(query, conn)

print(df)
# # Optional: one row per industry, one column per percentile
# wide = df.pivot(index="industry", columns="percentile", values="gap_days")
# print(wide)



churn_query = """
WITH cohort AS (
    SELECT customer_id,
           MIN(DATE(transaction_date)) AS cohort
    FROM my_table
    GROUP BY 1
),

-- transactions in the customer's first 30 days (used for bucketing)
first_month_txns AS (
    SELECT m.customer_id
    FROM my_table m
    JOIN cohort c
      ON c.customer_id = m.customer_id
     AND DATE(m.transaction_date) < DATE(c.cohort, '+30 days')
),

activity_first_month AS (
    SELECT customer_id,
           COUNT(*) AS first_month_activity
    FROM first_month_txns
    GROUP BY 1
),

first_month_bucket AS (
    SELECT customer_id,
           first_month_activity,
           CASE
               WHEN first_month_activity <= 3 THEN '1-3'
               WHEN first_month_activity <= 6 THEN '4-6'
               WHEN first_month_activity <= 9 THEN '7-9'
               ELSE '10+'
           END AS bucket
    FROM activity_first_month
),

totals AS (
    SELECT bucket,
           COUNT(*)                  AS n_customers,
           SUM(first_month_activity) AS n_transactions
    FROM first_month_bucket
    GROUP BY 1
),

-- FULL history: gaps are not limited to the first month
daily AS (
    SELECT customer_id, DATE(transaction_date) AS txn_date
    FROM my_table
    GROUP BY 1, 2
),

gaps AS (
    SELECT customer_id,
           julianday(txn_date)
             - julianday(LAG(txn_date) OVER (PARTITION BY customer_id ORDER BY txn_date)) AS gap
    FROM daily
),

ranked AS (
    SELECT b.bucket,
           g.gap,
           ROW_NUMBER() OVER (PARTITION BY b.bucket ORDER BY g.gap) AS rn,
           COUNT(*)     OVER (PARTITION BY b.bucket)                AS n
    FROM gaps g
    JOIN first_month_bucket b ON b.customer_id = g.customer_id
    WHERE g.gap IS NOT NULL
),

pcts(p) AS (
    VALUES (0.5), (0.75), (0.9), (0.95), (0.99)
)

SELECT r.bucket,
       pcts.p AS percentile,
       r.gap  AS gap_days
FROM ranked r
JOIN pcts
  ON r.rn = MAX(1, CAST(ROUND(pcts.p * r.n, 9) AS INTEGER)
                   + (ROUND(pcts.p * r.n, 9) > CAST(ROUND(pcts.p * r.n, 9) AS INTEGER)))
JOIN totals t
  ON t.bucket = r.bucket
ORDER BY CASE r.bucket WHEN '1-3' THEN 1 WHEN '4-6' THEN 2 WHEN '7-9' THEN 3 ELSE 4 END,
         pcts.p;
"""

df = pd.read_sql_query(churn_query, conn)
conn.close()

print(df)
wide = df.pivot(index="bucket", columns="percentile", values="gap_days")
print(wide)
