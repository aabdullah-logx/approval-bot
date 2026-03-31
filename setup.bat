@echo off

REM Navigate to the user's Desktop
cd %USERPROFILE%\Desktop

REM Create a new directory for the project and navigate into it
mkdir "Automated BOT for Approval"
cd "Automated BOT for Approval"

REM Clone the repository (Please authenticate if prompted)
echo Cloning the repository. Please wait...
git clone https://RahulLogx@bitbucket.org/crossing-borders-management-solutions/bot-for-automated-approval-sc.git

REM Wait for 60 seconds to allow time for authentication
echo Please authenticate within the next 60 seconds...
timeout /t 5

REM Install Virtual Environment
pip install virtualenv

REM Create a virtual environment named "venv"
virtualenv venv

REM Activate the virtual environment
call .\venv\Scripts\activate.bat

REM Navigate to the cloned repository
cd bot-for-automated-approval-sc

REM Install the required packages
pip install -r requirements.txt

REM Ask for server number and then add to server.py in the project root
set /p serverNum="Enter server number: "
echo server=%serverNum% > server.py

echo All tasks completed!
pause
