from google.cloud import bigquery
from config import Config
import os

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "credentials.json"

def get_bq_client():
    return bigquery.Client(project=Config.BQ_PROJECT)