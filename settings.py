import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# If LOCAL=True, store data is fetched from stores.csv (access_sc.py runs standalone)
# If LOCAL=False, store data is fetched from Google Sheets (approval.py handles it)
LOCAL = False

AMAZON_SC_BASE_URL = os.getenv('AMAZON_SC_BASE_URL', 'https://sellercentral.amazon.com/')
AMAZON_HOME = os.getenv('AMAZON_HOME', 'https://sellercentral.amazon.com/home')
AMAZON_LOGIN_URL = os.getenv('AMAZON_LOGIN_URL', 'signin?ref_=scus_soa_wp_signin_n')
APPROVAL_PAGE_URL = os.getenv('APPROVAL_PAGE_URL', 'fixyourproducts?ref_=myi_ia_vl_fba')
SELECT_ACC_URL = os.getenv('SELECT_ACC_URL', 'authorization/select-account?')
STORE_NAME = os.getenv('STORE_NAME', '')
STORE_EMAIL = os.getenv('STORE_EMAIL', 'Perfect.deal2204@gmail.com')
STORE_PASSWORD = os.getenv('STORE_PASSWORD', 'YKS$8450')
ACCOUNT_REGION = os.getenv('ACCOUNT_REGION', 'Canada')

url_template = {
    'approval_required':'''https://sellercentral.amazon.com/fixyourproducts/completeSkus?status=ISSUE_INACTIVE&pageSize={page_size}&offset={offset}&sortType=DATE&sortOrder=DESCENDING&searchTerm=null&searchType=null&filter=[{%22type%22:%22AGGREGATED_LISTING_STATUS%22,%22values%22:[%22INACTIVE_GATED%22]}]''',
    'pricing_issue':'''https://sellercentral.amazon.com/fixyourproducts/completeSkus?status=ISSUE_INACTIVE&pageSize={page_size}&offset={offset}&sortType=DATE&sortOrder=DESCENDING&searchTerm=null&searchType=null&filter=[{%22type%22:%22AGGREGATED_LISTING_STATUS%22,%22values%22:[%22INACTIVE_LOW_PRICE_WEAK_BLOCK%22,%22INACTIVE_HIGH_PRICE_WEAK_BLOCK%22]}]'''
}

token = os.getenv('GOLOGIN_TOKEN', 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI2NDI2ZmUxZjFkNGM5MTdhMmI1Y2ViNjYiLCJ0eXBlIjoiZGV2Iiwiand0aWQiOiI2OWM2YzFjMDllMTc1YTg1NWYyODU4MTYifQ.yz4fY07O9LusPMmhyle3FJ_OEEaNZAPg2jJ6yE360qE')

# stores = [
#     {'profile_id': '6452c0bb783d2408e55de6e2', 'profile_name': 'mega_star', 'email':'admin@metastarshop.org', 'pass':'NewGTA%5144'},
#     {'profile_id': '644acc8643a1970a7fe83f17', 'profile_name': 'chamaeleon_store'},
#     {'profile_id': '64381683b1ae0606bcdce0af','profile_name': 'shadow_star'},
#     {'profile_id': '64381630f9409b7797d17975','profile_name': 'galaxy_fire'},
# ]

json_gsheet_key = os.getenv('JSON_GSHEET_KEY')
folder_id = os.getenv('FOLDER_ID')

SLACK_BOT_TOKEN = os.getenv('SLACK_BOT_TOKEN')
SLACK_CHANNEL_ID = os.getenv('SLACK_CHANNEL_ID')
