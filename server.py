import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

server = int(os.getenv('SERVER_ID', '6'))
