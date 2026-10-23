import sqlite3
from pathlib import Path

import matplotlib
matplotlib.use("Agg")                       # works on a Linux server with no display
import matplotlib.pyplot as plt
import pandas as pd
from lifelines import KaplanMeierFitter
from lifelines.statistics import multivariate_logrank_test

# pip install lifelines pandas matplotlib


import pandas as pd

def build_survival_data(tx, churn_days=None, default_churn_days=150):
    """One row per customer with the two things a Kaplan-Meier model needs:

    duration : days from first transaction until the customer's last transaction (if churned)
               or until the end of the data (if still active)
    event    : 1 = churned (no transaction for more than the industry's churn threshold
                   before the end of the data)
               0 = censored (still active, or too recent to know)

    churn_days : dict mapping industry -> churn threshold in days,
                 e.g. {"Retail": 45, "Banking": 120, "Telecom": 60}.
                 A single int is also accepted and applied to every industry.
    default_churn_days : threshold used for any industry missing from the dict.
    """
    tx = tx.copy()
    tx.columns = [c.lower() for c in tx.columns]      # so Customer_ID / Customer_id both work
    tx["transaction_date"] = pd.to_datetime(tx["transaction_date"])
    end_date = tx["transaction_date"].max()
    print(end_date)

    cust = (tx.sort_values("transaction_date")
              .groupby("customer_id")
              .agg(first_txn=("transaction_date", "min"),
                   last_txn=("transaction_date", "max"),
                   bucket=("bucket", "first")))

    # Resolve the churn threshold for each customer based on their industry
    if churn_days is None:
        cust["churn_days"] = default_churn_days
    elif isinstance(churn_days, dict):
        cust["churn_days"] = cust["bucket"].map(churn_days).fillna(default_churn_days)
    else:
        cust["churn_days"] = churn_days

    print(cust)
    days_idle = (end_date - cust["last_txn"]).dt.days
    cust["event"] = (days_idle > cust["churn_days"]).astype(int)
    cust["duration"] = ((cust["last_txn"] - cust["first_txn"]).dt.days
                        .where(cust["event"] == 1, (end_date - cust["first_txn"]).dt.days))
    return cust


def fit_km(surv, by=None):
    """Fit Kaplan-Meier curve(s). Returns {label: fitted model}."""
    groups = {"All customers": surv} if by is None else dict(tuple(surv.groupby(by)))
    fitted = {}
    for label, g in groups.items():
        kmf = KaplanMeierFitter(label=str(label))
        kmf.fit(g["duration"], event_observed=g["event"])
        fitted[label] = kmf
    return fitted


def survival_summary(fitted, days=(60,90, 180, 365, 545)):
    """Share of customers still active at the given number of days, plus median lifetime."""
    rows = {}
    for label, kmf in fitted.items():
        row = {f"{d}d": round(float(kmf.predict(d)) * 100, 1) for d in days}
        row["median_days"] = kmf.median_survival_time_
        rows[label] = row
    return pd.DataFrame(rows).T


def plot_km(fitted, path, title="Survival Rate By Industry", ci=False):
    path = Path(path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 6))
    for kmf in fitted.values():
        kmf.plot_survival_function(ax=ax, ci_show=ci)
    ax.set_xlabel("Days since first transaction")
    ax.set_ylabel("Share of customers still active")
    ax.set_ylim(0, 1)
    ax.set_title(title)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


# --- Example -----------------------------------------------------------------
if __name__ == "__main__":
    conn = sqlite3.connect("clean_data.db")                       # <- your connection
    first_month_activation_query = """
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
)

SELECT m.customer_id,
       m.transaction_date,
       m.amount,
       f.bucket
FROM my_table m
INNER JOIN first_month_bucket f
        ON f.customer_id = m.customer_id;
"""

    tx = pd.read_sql_query(first_month_activation_query, conn)             # same cleaning as your cohort query
    print(tx)

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
    VALUES (0.99)
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
    df_churn = pd.read_sql_query(churn_query,conn)
    churn_dict = df_churn.set_index('bucket')['gap_days'].to_dict()

   
    #print(churn_dict)
    surv = build_survival_data(tx,churn_days= churn_dict)
    #print(surv)
    #surv.to_csv('Survival.csv')

    km_all = fit_km(surv)                                            # one overall curve
    km_ind = fit_km(surv, by="bucket")                             # one curve per industry

    print(survival_summary(km_ind)) 
    print(survival_summary(km_all))                                       # % active at 90/180/365/545 days
    plot_km(km_ind,  "Survival by bucket", title = "Survival Rate By No. Of Transactions in the First Month")
    plot_km(km_all, "Survival")
    # Are the industry curves statistically different?
    test = multivariate_logrank_test(surv["duration"], surv["bucket"], surv["event"])
    print("log-rank p-value:", test.p_value)