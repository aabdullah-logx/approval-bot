# Amazon Seller Central Automation Bot

## Setup Instructions

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment Variables
All configuration settings are stored in the `.env` file. Update the values as needed:

- **Amazon Settings**: URLs and credentials for Amazon Seller Central
- **GoLogin Token**: Your GoLogin API token for browser automation
- **Google Sheets/Drive**: Credentials and folder IDs for data storage
- **Slack**: Bot token and channel ID for notifications
- **Server ID**: Unique identifier for this server instance
- **Chrome Driver**: Paths to ChromeDriver executables for different platforms

### 3. Required Files
Make sure these files exist in your project directory:
- `client_secret.json` - Google OAuth credentials
- `chromedriver.exe` / `chromedriver_linux` / `chromedriver` - ChromeDriver executable
- `stores.csv` - Store configuration (managed via Google Sheets)

### 4. Run the Bot
```bash
python approval.py
```

## Environment Variables

All sensitive data and configuration is now stored in `.env` file. Never commit this file to version control!

Key variables:
- `GOLOGIN_TOKEN` - GoLogin API authentication token
- `SLACK_BOT_TOKEN` - Slack bot OAuth token
- `FOLDER_ID` - Google Drive folder ID for storing reports
- `SERVER_ID` - Server identifier for multi-instance deployments

## Security Notes

- The `.env` file contains sensitive credentials and should be added to `.gitignore`
- Never share your `.env` file or commit it to version control
- Rotate tokens and passwords regularly
# approval-bot
