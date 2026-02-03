import os
from dotenv import load_dotenv
load_dotenv()

JWT_SECRET_KEY = str(os.getenv('JWT_SECRET_KEY'))
JWT_ALGORITHM = str(os.getenv('JWT_ALGORITHM'))
ACCESS_TOKEN_EXPIRE_MINUTES = 15
DATABASE_URL=os.getenv('DATABASE_URL')
FRONTEND_URL=os.getenv('FRONTEND_URL')
SMTP_HOST = os.getenv('SMTP_HOST')
SMTP_PORT = os.getenv('SMTP_PORT')
SMTP_USER = os.getenv('SMTP_USER')
SMTP_PASS = os.getenv('SMTP_PASS')