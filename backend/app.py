from flask import Flask
from flask_cors import CORS
from routes import register_routes
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)  # This enables CORS for all routes

register_routes(app)

if __name__ == "__main__":
    app.run(debug=True, port=5000)