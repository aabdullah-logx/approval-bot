import traceback
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
import settings

def send_slack_message(message: str):
    """
    Sends a simple text message to the configured Slack channel.
    """
    if not settings.SLACK_BOT_TOKEN or not settings.SLACK_CHANNEL_ID:
        print("Warning: Slack Token or Channel ID is missing. Skipping notification.")
        return False
    return None

    # client = WebClient(token=settings.SLACK_BOT_TOKEN)
    #
    # try:
    #     response = client.chat_postMessage(
    #         channel=settings.SLACK_CHANNEL_ID,
    #         text=message
    #     )
    #     print("Slack notification sent successfully!")
    #     return True
    # except SlackApiError as e:
    #     print(f"Error sending Slack notification: {e.response['error']}")
    #     return False
    # except Exception as e:
    #     print(f"Unexpected error when sending Slack notification: {e}")
    #     traceback.print_exc()
    #     return False
