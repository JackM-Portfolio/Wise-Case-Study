import sqlite3
import pandas as pd

conn = sqlite3.connect("clean_data.db")   # <- your connection

# Customer lifetime value (LTV) by industry.
#   Realised LTV : total net transaction value per customer over their whole history (Amount is in GBP).
#                  Customers who are still active have not finished yet, so treat it as "value so far".
#   12-month LTV : value in each customer's first 365 days, using only customers acquired at least
#                  365 days before the end of the data. This is the like-for-like comparison.

ltv_query = """
with bounds as (
SELECT max(date(transaction_date)) as max_date
FROM my_table
),

cohort AS (
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

transactionss as (
SELECT m.customer_id
       ,m.transaction_date
       ,m.amount
       ,f.bucket as industry
FROM my_table m
INNER JOIN first_month_bucket f ON f.customer_id = m.customer_id
),
-- one row per customer (a handful of customers appear under two industries; min() picks one)
customer as (
SELECT Customer_id
    ,min(Industry) as Industry
    ,min(date(transaction_date)) as first_txn
    ,max(date(transaction_date)) as last_txn
    ,count(*) as txns
    ,sum(Amount) as total_value
FROM transactionss
Group by Customer_id
),


-- value in the first 365 days after acquisition
first_12m as (
SELECT c.Customer_id
    ,sum(t.Amount) as value_12m
FROM customer c
JOIN transactionss t
  ON t.Customer_id = c.Customer_id
 AND date(t.transaction_date) < date(c.first_txn, '+365 days')
Group by c.Customer_id
),


ranked as (
SELECT Industry
    ,total_value
    ,row_number() over (partition by Industry order by total_value) as rn
    ,count(*) over (partition by Industry) as cnt
FROM customer
),


medians as (
SELECT Industry
    ,avg(total_value) as median_ltv
FROM ranked
WHERE rn in ((cnt + 1) / 2, (cnt + 2) / 2)
Group by Industry
),


industry_summary as (
SELECT c.Industry
    ,count(*) as customers
    ,sum(c.total_value) as total_value
    ,avg(c.total_value) as avg_ltv
    ,avg(c.txns) as avg_txns
    ,sum(c.total_value) / sum(c.txns) as avg_txn_size
    ,avg(julianday(c.last_txn) - julianday(c.first_txn)) as avg_lifetime_days
    ,avg(case when c.first_txn <= date(b.max_date, '-365 days') then f.value_12m end) as avg_12m_ltv
    ,sum(case when c.first_txn <= date(b.max_date, '-365 days') then 1 else 0 end) as customers_in_12m_calc
FROM customer c
JOIN first_12m f ON f.Customer_id = c.Customer_id
CROSS JOIN bounds b
Group by c.Industry
)


SELECT s.Industry
    ,s.customers
    ,round(s.avg_ltv, 0) as avg_ltv
    ,round(m.median_ltv, 0) as median_ltv
    ,round(s.avg_12m_ltv, 0) as avg_12m_ltv
    ,s.customers_in_12m_calc
    ,round(s.avg_txns, 1) as avg_txns
    ,round(s.avg_txn_size, 0) as avg_txn_size
    ,round(s.avg_lifetime_days, 0) as avg_lifetime_days
    ,round(s.total_value, 0) as total_value
    ,round(100.0 * s.total_value / sum(s.total_value) over (), 1) as pct_of_total_value
FROM industry_summary s
JOIN medians m ON m.Industry = s.Industry
ORDER BY s.avg_ltv desc
"""

ltv = pd.read_sql_query(ltv_query, conn)
print(ltv)
ltv.to_csv("lifetime.csv")
# print(ltv.to_string(index=False))