from pyspark import pipelines as dp
from pyspark.sql import SparkSession

spark = SparkSession.getActiveSession()

@dp.table
def sample_aggregation_jun_10_redeploy_test():
    return spark.range(10)