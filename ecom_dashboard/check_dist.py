import duckdb
con = duckdb.connect('E:/ecom_dashboard/ecom_dashboard/Files/unified_orders_and_listings.duckdb')
df = con.execute('SELECT "Market - Store Name", COUNT(*) FROM unified_data GROUP BY 1').fetchdf()
print(df)
