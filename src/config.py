import os

from dotenv import load_dotenv


load_dotenv(".env")

LOG_LEVEL=os.getenv('LOG_LEVEL', 'DEBUG')
