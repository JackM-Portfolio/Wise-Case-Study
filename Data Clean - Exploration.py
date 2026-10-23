import sqlite3
import pandas as pd



conn = sqlite3.connect("mydata.db")

gaps_query = """
WITH cleaned_table AS (
    SELECT DISTINCT *
    FROM my_table
    WHERE transaction_date >= '2019-01-01'
),

industry as (
SELECT m.customer_id
        ,m.industry
       ,count(*) as app
FROM my_table m
INNER JOIN cleaned_table c on c.customer_id = m.customer_id
group by 1,2),

industry_rank as (
SELECT *
       ,ROW_NUMBER() OVER(PARTITION BY customer_ID order by app desc) as rn
FROM industry),

industry_selected as (
SELECT *
FROM industry_rank 
WHERE rn = 1
)

SELECT c.customer_id
       ,c.transaction_date
       ,c.amount
       ,i.industry
FROM cleaned_table c
LEFT JOIN industry_selected i on c.customer_id = i.customer_id

"""

df = pd.read_sql_query(gaps_query,conn)
 #df.pivot(index='bucket',columns= 'p').to_csv('Monthly Activation.csv')
conn.close()

clean_conn = sqlite3.connect("clean_data.db")
df.to_sql("my_table", clean_conn, if_exists="replace", index=False)
clean_conn.close()


