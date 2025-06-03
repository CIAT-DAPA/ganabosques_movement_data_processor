import os
from dotenv import load_dotenv

load_dotenv()

config = {}

config['DEBUG'] = os.getenv('DEBUG', 'true').lower() == 'true'
config['WORKSPACE'] = os.getenv('WORKSPACE')
config['DATA'] = os.getenv('DATA')
config['MONGO_URI'] = os.getenv('MONGO_URI')
config['MONGO_DB_NAME'] = os.getenv('MONGO_DB_NAME')


if __name__ == "__main__":
    print(config)