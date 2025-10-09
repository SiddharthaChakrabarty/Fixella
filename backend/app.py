from flask import Flask, jsonify, render_template
import os, json

app = Flask(__name__, static_folder='static', template_folder='templates')
DATA_FILE = os.path.join(os.path.dirname(__file__), 'it_tickets_kb.json')

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/tickets')
def tickets():
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            tickets = json.load(f)
    except Exception:
        tickets = []
    return jsonify(tickets)

if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1', port=5000)
