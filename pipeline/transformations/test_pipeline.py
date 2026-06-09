from pyspark import pipelines as dp
from pyspark.sql import SparkSession

spark = SparkSession.getActiveSession()

@dp.table
def test_table():
    return spark.range(10)