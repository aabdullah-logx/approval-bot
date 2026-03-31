import cv2
import re
import pyotp
import os

def get_secret_key(uri):
    match = re.search(r'secret=([^&]+)', uri)
    if match:
        secret_key = match.group(1)
        return secret_key
    else:
        raise ValueError("Secret key not found in the OTPAuth URI.")
    

# Load the QR code image
def generate_qr_key(image):
    try:
        # Initialize the QR code detector
        detector = cv2.QRCodeDetector()

        # Detect and decode the QR code
        val = detector.detectAndDecode(image)

        key = get_secret_key(val[0])

        return key
    except Exception as e:
        print(f'Error: {e}')
        return None

def generate_2fa_code(key):
    try:
        # Initialize the TOTP object
        totp = pyotp.TOTP(key)

        # Generate the Google Authenticator code
        code_2fa = totp.now()

        return code_2fa
    except Exception as e:
        print(f'Error: {e}')
        return None

def download_image_from_gdrive_and_load(file_id, drive, temp_image_path='temp_image.png'):
 
    try:
        # Download the file from Google Drive
        file = drive.CreateFile({'id': file_id})
        file.GetContentFile(temp_image_path)  # Save the file to a temporary path

        # Load the image with OpenCV
        image = cv2.imread(temp_image_path)

        # Optionally, remove the temporary file after loading
        os.remove(temp_image_path)

        return image
    except Exception as e:
        print(f"An error occurred while downloading or loading the image: {e}")
        return None
    
def main():
    key = 'AL4Q5U4FR4DA2TYWIWXGXT47ONIUECK5KOXOAACV7KM2HW6W6EEA'
    totp = generate_2fa_code(key)
    print(totp)

if __name__ == "__main__":
    main()
